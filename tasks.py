import logging
import json
import os
from app import celery, db, Submission, LeaderboardMetric, MetricResult, Sample, app, CustomField
from metric_engine import (evaluate_dynamic_metric, sort_metrics_by_dependency, apply_gt_source,
                           MetricContextBuilder, GtSourceContextBuilder)
import numpy as np

# Configure logging
logger = logging.getLogger(__name__)


def publish_metric_value(ctx, metric_out_name, friendly_out_name, value):
    """
    Write a metric's result into a per-sample context under EVERY name another
    metric might map to it by.

    This must match what MetricContextBuilder produces when it reads the same
    value back from a stored CustomField on a later run — "lm_<id>", "<name>",
    and both with the "sub_" prefix. When it didn't, a dependent metric worked on
    recalculation (reading the previous run's stored row, which had all four
    aliases) but failed on a fresh submission (where only two were published and
    nothing was stored yet).
    """
    for key in (metric_out_name, friendly_out_name):
        if key:
            ctx[key] = value
            ctx[f"sub_{key}"] = value

@celery.task(bind=True, max_retries=5, ignore_result=True)
def process_submission(self, submission_id, sample_filters=None):
    # Force remove any existing session to avoid issues in some Celery environments
    db.session.remove()
    session = db.session
    try:
        submission = session.query(Submission).get(submission_id)
        if not submission:
            logger.info(f"Submission {submission_id} not found in task. Retrying...")
            try:
                self.retry(countdown=1)
            except self.MaxRetriesExceededError:
                logger.error(f"Submission {submission_id} not found after retries.")
            return

        submission.processing_status = 'Processing'
        session.commit() # Commit the status change
        
        # --- Metric Calculation Logic ---
        leaderboard = submission.leaderboard
        if not leaderboard.leaderboard_metrics:
            logger.info(f"No metrics defined for leaderboard {leaderboard.id}. Skipping calculation.")
        else:
            # Fetch all samples for this dataset(s)
            dataset_ids = [d.id for d in leaderboard.datasets] if leaderboard.datasets else [leaderboard.dataset_id]
            dataset_samples_query = session.query(Sample).filter(Sample.dataset_id.in_(dataset_ids))
            
            # Apply filters if provided
            if sample_filters:
                # 1. Search Filter (by name)
                if sample_filters.get('search'):
                    dataset_samples_query = dataset_samples_query.filter(Sample.name.ilike(f"%{sample_filters['search']}%"))
                
                # 2. Tag Filters
                def tag_match_filter(tag):
                    from sqlalchemy import or_
                    return or_(
                        Sample.tags == tag,
                        Sample.tags.ilike(f'{tag},%'),
                        Sample.tags.ilike(f'%,{tag}'),
                        Sample.tags.ilike(f'%,{tag},%')
                    )

                include = sample_filters.get('include', {})
                if include.get('enabled') and include.get('tags'):
                    for tag in include['tags']:
                        dataset_samples_query = dataset_samples_query.filter(tag_match_filter(tag))
                
                exclude = sample_filters.get('exclude', {})
                if exclude.get('enabled') and exclude.get('tags'):
                    from sqlalchemy import or_, not_
                    exclude_conditions = [tag_match_filter(tag) for tag in exclude['tags']]
                    dataset_samples_query = dataset_samples_query.filter(not_(or_(*exclude_conditions)))

                prefix = sample_filters.get('prefix', {})
                if prefix.get('enabled') and prefix.get('tags'):
                    from sqlalchemy import or_
                    for p in prefix['tags']:
                        dataset_samples_query = dataset_samples_query.filter(or_(
                            Sample.tags.ilike(f'{p}%'),
                            Sample.tags.ilike(f'%,{p}%'),
                            Sample.tags.ilike(f'%, {p}%')
                        ))

            dataset_samples = dataset_samples_query.all()
            logger.info(f"Filtered to {len(dataset_samples)} samples for metrics calculation.")

            # Store the filters used for this calculation
            submission.last_sample_filter = json.dumps(sample_filters, sort_keys=True) if sample_filters else None
            
            # Submission folder path
            submission_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'submissions', str(submission.id))
            
            logger.info(f"Building context for {len(dataset_samples)} samples from folder: {submission_folder}")
            samples_context = MetricContextBuilder(
                dataset_samples, submission, submission_folder=submission_folder
            ).contexts_for_all()


            if not samples_context:
                 logger.warning(f"No samples matched filters for submission {submission.id}. Metrics will be null.")

            # GT-source overrides: a metric may read its gt_* args from another
            # submission instead of the dataset. Built lazily (and cached) per
            # source submission, aligned index-for-index with dataset_samples.
            gt_override_cache = {}

            def gt_overrides_for(gt_sub):
                if gt_sub.id not in gt_override_cache:
                    gt_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'submissions', str(gt_sub.id))
                    gt_override_cache[gt_sub.id] = GtSourceContextBuilder(
                        dataset_samples, gt_sub, submission_folder=gt_folder
                    ).overrides_for_all()
                return gt_override_cache[gt_sub.id]

            # Sort metrics by dependency
            sorted_metrics = sort_metrics_by_dependency(leaderboard.leaderboard_metrics)
            # Keyed by every alias publish_metric_value() writes, so an aggregated
            # metric consumed via a prefixed/id mapping (sub_<name>, lm_<id>,
            # sub_lm_<id>) is still recognised as aggregated. Keyed by the friendly
            # name alone, those mappings fell through to the per-sample branch and
            # received a list of the same scalar repeated once per sample.
            metric_is_agg_map = {}
            for lm in leaderboard.leaderboard_metrics:
                 name = lm.target_name if lm.target_name else lm.global_metric.name
                 for key in (name, f"sub_{name}", f"lm_{lm.id}", f"sub_lm_{lm.id}"):
                     metric_is_agg_map[key] = lm.global_metric.is_aggregated
            
            logger.info(f"Evaluating {len(sorted_metrics)} leaderboard metrics...")

            for lm in sorted_metrics:
                global_metric = lm.global_metric
                arg_mappings_json = lm.arg_mappings
                metric_out_name = f"lm_{lm.id}"
                friendly_out_name = lm.target_name if lm.target_name else lm.global_metric.name

                # Check for existing result
                existing_result = session.query(MetricResult).filter_by(
                    submission_id=submission.id, 
                    leaderboard_metric_id=lm.id
                ).first()
                if existing_result:
                    session.delete(existing_result)
                
                # Tag-based filtering for this specific metric
                current_metric_samples = dataset_samples
                current_metric_ctx = samples_context
                current_indices = list(range(len(dataset_samples)))

                if hasattr(lm, 'tag_filter') and lm.tag_filter:
                    tags = [t.strip().lower() for t in lm.tag_filter.split(',')]
                    include_tags = [t for t in tags if not t.startswith('!')]
                    exclude_tags = [t[1:] for t in tags if t.startswith('!')]
                    
                    filtered_indices = []
                    for i, sample in enumerate(dataset_samples):
                        sample_tags = [t.strip().lower() for t in (sample.tags.split(',') if sample.tags else [])]
                        
                        # Check excludes
                        if any(t in sample_tags for t in exclude_tags):
                            continue
                        
                        # Check includes
                        if not include_tags or any(t in sample_tags for t in include_tags):
                            filtered_indices.append(i)
                    
                    current_metric_samples = [dataset_samples[i] for i in filtered_indices]
                    current_metric_ctx = [samples_context[i] for i in filtered_indices]
                    current_indices = filtered_indices

                    logger.info(f"  [Metric: {metric_out_name}] Filtered to {len(current_metric_samples)}/{len(dataset_samples)} samples due to tag_filter: {lm.tag_filter}")

                value = None
                error = None

                # Contexts used for THIS metric's evaluation. With a GT source
                # submission these are copies with gt_* swapped out; results are
                # still written back to current_metric_ctx so later metrics that
                # depend on this one see the value in the shared context.
                eval_contexts = current_metric_ctx
                gt_sub = getattr(lm, 'gt_source_submission', None)
                if lm.gt_source_submission_id and not gt_sub:
                    error = f"GT source submission {lm.gt_source_submission_id} no longer exists."
                    logger.warning(f"  [Metric: {metric_out_name}] {error}")
                    session.add(MetricResult(
                        submission_id=submission.id,
                        leaderboard_metric_id=lm.id,
                        value=None,
                        error_message=error
                    ))
                    continue
                if gt_sub:
                    overrides = gt_overrides_for(gt_sub)
                    eval_contexts = [apply_gt_source(ctx, overrides[current_indices[j]])
                                     for j, ctx in enumerate(current_metric_ctx)]
                    logger.info(f"  [Metric: {metric_out_name}] Using submission '{gt_sub.name}' (id={gt_sub.id}) as GT source.")

                if global_metric.is_aggregated:
                    agg_context = {}
                    try:
                         mappings = json.loads(arg_mappings_json)
                         required_keys = mappings.values()
                    except:
                         required_keys = []
                    
                    for key in required_keys:
                        is_agg_input = metric_is_agg_map.get(key, False)
                        if is_agg_input:
                            if eval_contexts:
                                agg_context[key] = eval_contexts[0].get(key, None)
                            else:
                                agg_context[key] = None
                        else:
                            vals = []
                            for ctx in eval_contexts:
                                vals.append(ctx.get(key, None))
                            agg_context[key] = vals

                    value, error = evaluate_dynamic_metric(global_metric, agg_context, arg_mappings_json)
                    logger.info(f"  [Metric: {metric_out_name}] Aggregated calculation. Value: {value}")
                    if value is not None:
                        # Update ALL samples with the aggregated value for this metric.
                        for ctx in samples_context:
                            publish_metric_value(ctx, metric_out_name, friendly_out_name, value)
                else:
                    # Per-sample: Average the results
                    sample_values = []
                    sample_errors = []
                    
                    # Cleanup existing CustomFields for this metric to avoid stale data
                    session.query(CustomField).filter_by(
                         submission_id=submission.id, 
                         name=metric_out_name
                    ).delete(synchronize_session=False)

                    for i, eval_ctx in enumerate(eval_contexts):
                        val, err = evaluate_dynamic_metric(global_metric, eval_ctx, arg_mappings_json)
                        if val is not None:
                            sample_values.append(val)
                            # Write back to the shared per-sample context (eval_ctx
                            # may be a GT-source copy), so dependent metrics see it.
                            publish_metric_value(current_metric_ctx[i], metric_out_name,
                                                 friendly_out_name, val)
                            
                            # Persist to CustomField for Visualization
                            try:
                                current_sample = current_metric_samples[i]
                                cf = CustomField(
                                    submission_id=submission.id,
                                    sample_id=current_sample.id,
                                    sample_name=current_sample.name,
                                    name=metric_out_name,
                                    field_type='scalar',
                                    value_float=float(val)
                                )
                                session.add(cf)
                            except Exception as e:
                                logger.error(f"Error persisting custom field {metric_out_name} for sample {i}: {e}")

                        if err:
                            sample_errors.append(err)
                    
                    if sample_values:
                        # Aggregation Logic
                        pooling_type = getattr(lm, 'pooling_type', 'mean')
                        pooling_percentile = getattr(lm, 'pooling_percentile', None)
                        
                        try:
                            if pooling_type == 'median':
                                value = float(np.median(sample_values))
                                agg_desc = "Median"
                            elif pooling_type == 'percentile' and pooling_percentile is not None:
                                value = float(np.percentile(sample_values, pooling_percentile))
                                agg_desc = f"{pooling_percentile}th Percentile"
                            else:
                                # Default to Mean
                                value = float(np.mean(sample_values))
                                agg_desc = "Mean"
                                
                            logger.info(f"  [Metric: {metric_out_name}] Per-sample {agg_desc} of {len(sample_values)} samples. Result: {value}")
                        except Exception as e:
                            logger.error(f"  [Metric: {metric_out_name}] Aggregation ({pooling_type}) failed: {e}")
                            value = None
                            error = f"Aggregation failed: {str(e)}"

                    elif sample_errors:
                        error = sample_errors[0]
                        logger.warning(f"  [Metric: {metric_out_name}] Per-sample calculation failed. Error: {error}")
                
                # Store Result
                result = MetricResult(
                    submission_id=submission.id,
                    leaderboard_metric_id=lm.id,
                    value=value,
                    error_message=error
                )
                session.add(result)
            
            session.commit()
        
        # Update Submission with filter state
        if sample_filters:
            submission.last_sample_filter = json.dumps(sample_filters)
        else:
            submission.last_sample_filter = None
            
        submission.processing_status = 'Processed'
        session.commit()
        logger.info(f"Processing submission {submission_id} done.")

    except Exception as e:
        session.rollback()
        try:
           submission = session.query(Submission).get(submission_id)
           if submission:
               submission.processing_status = f'Error: {e}'
               session.commit()
        except Exception as inner_e:
            logger.critical(f"Critical error updating submission status: {inner_e}")
        logger.exception(f"Error processing submission {submission_id}: {e}")
    finally:
        session.remove()
