import traceback
import json
import numpy as np
import os
import sys


def _app_module():
    """
    Return the module that owns the LIVE Flask app and SQLAlchemy instance.

    app.py registers itself in sys.modules as "app" when it runs as __main__, so
    a plain `import app` already resolves correctly under every entry point
    (`python app.py`, Celery, WSGI). This is the backstop for the case that
    registration is bypassed — app.py loaded as __main__ without the alias would
    otherwise be imported a second time here, yielding a duplicate SQLAlchemy()
    that is not bound to the running app ("The current Flask app is not
    registered with this 'SQLAlchemy' instance").
    """
    main = sys.modules.get('__main__')
    if (main is not None and hasattr(main, 'db')
            and os.path.basename(getattr(main, '__file__', '') or '') == 'app.py'):
        return main
    import app
    return app

# Compiled metric/visualization code, keyed by source text.
_COMPILED_CODE_CACHE = {}
_COMPILED_CODE_CACHE_MAX = 256


def _compiled_metric_code(source):
    """compile() the given source once and reuse it. Keyed by the source itself,
    so an edited metric compiles fresh rather than serving a stale code object."""
    code_obj = _COMPILED_CODE_CACHE.get(source)
    if code_obj is None:
        code_obj = compile(source, '<dynamic_metric>', 'exec')
        if len(_COMPILED_CODE_CACHE) >= _COMPILED_CODE_CACHE_MAX:
            _COMPILED_CODE_CACHE.clear()
        _COMPILED_CODE_CACHE[source] = code_obj
    return code_obj


def _unresolved_mapping_hint(unresolved, context):
    """
    Explain which arguments were passed as None and why, so a failure inside the
    metric (AssertionError, TypeError on None, ...) points at the real cause.
    """
    lines = ["Unresolved argument mappings — these were passed to the metric as None:"]
    for arg, key in unresolved:
        lines.append(f"    {arg} -> '{key}'   (no such key in this sample's context)")

    if any(key.startswith('gt_') for _, key in unresolved):
        lines.append(
            "  A gt_* mapping is missing. If this metric uses a submission as its Ground Truth "
            "Source, its gt_* arguments must name fields THAT submission provides — the dataset's "
            "own gt_* values are deliberately NOT used as a fallback, so a mapping left pointing "
            "at a dataset field name resolves to nothing. Check the metric's argument mappings in "
            "the leaderboard settings, and that the source submission has been processed and has "
            "this field for this sample. Only scalar/metric fields are available as gt_*/sub_* "
            "values; image and depth fields are not. Raw histogram counts are available "
            "as gt_hist / sub_hist_<folder> / gt_hist_<folder>, alongside the derived "
            "gt_entropy / sub_entropy_<folder>.")

    keys = sorted(context)
    shown = ', '.join(keys[:40]) + (f"  ... (+{len(keys) - 40} more)" if len(keys) > 40 else '')
    lines.append(f"  Context keys available for this sample: {shown or '(none)'}")
    return '\n'.join(lines)


def evaluate_dynamic_metric(global_metric, context, arg_mappings_json):
    """
    Evaluates a GlobalMetric's python_code against the provided context.
    """
    unresolved = []
    context = context or {}
    try:
        # Parse mappings
        try:
            arg_mappings = json.loads(arg_mappings_json)
        except:
            arg_mappings = {}

        # Prepare arguments
        call_kwargs = {}
        for arg, mapping_key in arg_mappings.items():
            if mapping_key.startswith('SCALAR:'):
                val_str = mapping_key[7:] # len('SCALAR:') == 7
                try:
                    # Try float first
                    val = float(val_str)
                    # Optional: if int, convert to int?
                    if val.is_integer():
                        val = int(val)
                    call_kwargs[arg] = val
                except ValueError:
                    # Fallback to string if not numeric
                    call_kwargs[arg] = val_str
            elif mapping_key not in context:
                 # Unresolved mapping. Still passed as None so metrics with
                 # optional arguments keep working, but recorded so that a
                 # failure inside the metric can name the empty argument instead
                 # of surfacing a bare AssertionError/TypeError from user code.
                 unresolved.append((arg, mapping_key))
                 call_kwargs[arg] = None
            else:
                 call_kwargs[arg] = context[mapping_key]
        
        # Execute code. The compiled form is cached by source text (so editing a
        # metric naturally invalidates it) — this runs once per sample per metric,
        # and re-parsing the source every time was pure overhead.
        local_scope = {'np': np} # Inject common libs
        exec(_compiled_metric_code(global_metric.python_code), local_scope)
        
        # Find the function (assuming name matches or it's the only one?)
        # Convention: The code defines a function. We can find it by name if we knew it,
        # or just take the last defined function.
        # But 'global_metric.name' might not match function name if user edited code freely.
        # Let's inspect local_scope for callables.
        
        # Ideally, we should enforce function name = metric name or something.
        # Or look for a callable that isn't 'np'.
        func = None
        for k, v in local_scope.items():
            if callable(v) and k != 'np':
                func = v
                break
        
        if not func:
            return None, "No callable function found in code."

        # Call it
        result = func(**call_kwargs)
        
        # Handle nan/inf
        if isinstance(result, float) and (np.isnan(result) or np.isinf(result)):
             return None, "Result is NaN or Inf"

        return float(result), None

    except Exception as e:
        detail = traceback.format_exc()
        if unresolved:
            detail += '\n' + _unresolved_mapping_hint(unresolved, context)
        print(f"DEBUG: Error evaluating metric {global_metric.name}: {e}"
              + (f" [unresolved args: {', '.join(a for a, _ in unresolved)}]" if unresolved else ""))
        return None, detail


def mapped_context_keys(leaderboard_metrics):
    """
    Every context key the given metrics bind an argument to. Feed this to the
    context builders as `needed_keys` so they know whether to retain the raw
    histogram arrays (gt_hist / sub_hist_<folder> / gt_hist_<folder>).
    """
    keys = set()
    for lm in leaderboard_metrics or ():
        try:
            keys.update(json.loads(getattr(lm, 'arg_mappings', None) or '{}').values())
        except Exception:
            pass
    return keys


def _entropy_from_counts(counts):
    """Shannon entropy (bits) of a histogram's counts. 0.0 for an empty histogram."""
    counts = np.asarray(counts)
    counts = counts[counts > 0]
    total = counts.sum()
    if total > 0:
        p = counts / total
        return float(-np.sum(p * np.log2(p)))
    return 0.0


def _chunked(seq, size=400):
    """SQLite caps the number of bound parameters, so IN (...) lists are chunked."""
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _hist_folders(submission_folder):
    """Histogram folders (hist_* / raw_histogram) directly under a submission."""
    try:
        return [f for f in os.listdir(submission_folder)
                if os.path.isdir(os.path.join(submission_folder, f))
                and (f.startswith('hist_') or f == 'raw_histogram')]
    except Exception as e:
        print(f"DEBUG: Error scanning submission folder for histograms: {e}")
        return []


def _submission_field_index(sub, sample_names):
    """
    {sample_name: [(field_name, value), ...]} plus {lm_<id>: friendly name} for a
    submission, in one pass instead of re-walking sub.custom_fields per sample.
    """
    _app = _app_module()
    db, CustomField, LeaderboardMetric = _app.db, _app.CustomField, _app.LeaderboardMetric
    by_sample = {}
    for chunk in _chunked(sample_names):
        rows = db.session.query(
            CustomField.sample_name, CustomField.name, CustomField.value_float
        ).filter(
            CustomField.submission_id == sub.id,
            CustomField.field_type.in_(['metric', 'scalar']),
            CustomField.sample_name.in_(chunk)
        ).order_by(CustomField.id).all()
        for sample_name, name, value_float in rows:
            by_sample.setdefault(sample_name, []).append((name, value_float))

    # lm_<id> -> friendly name, resolved once for the whole submission rather
    # than with a query per (sample, field).
    lm_ids = set()
    for fields in by_sample.values():
        for name, _ in fields:
            if name.startswith('lm_') and name[3:].isdigit():
                lm_ids.add(int(name[3:]))
    friendly = {}
    if lm_ids:
        for chunk in _chunked(lm_ids):
            for lm in LeaderboardMetric.query.filter(LeaderboardMetric.id.in_(chunk)).all():
                friendly[f"lm_{lm.id}"] = lm.target_name or lm.global_metric.name
    return by_sample, friendly


class MetricContextBuilder:
    """
    Builds per-sample metric contexts for a known set of samples.

    The per-sample work used to include a full scan of the submission's
    CustomField collection and two round-trips through the Sample.histogram_data
    property, which made metric calculation quadratic in dataset size. This does
    those lookups once and then serves each sample from dicts.

    Contexts are identical to what the per-sample code produced — including the
    quirk that gt_* keys can come from submission rows (CustomField.sample_id is
    set on submission rows too, and Sample.custom_fields matches on sample_id
    alone, so a submission field "x" also lands in "gt_x", last row by id
    winning). Existing metrics may rely on it, so it is preserved verbatim.

    Indexes are built lazily on first use and held for the builder's lifetime —
    construct one per calculation pass, not one that outlives a request/task.
    """

    def __init__(self, samples, sub=None, submission_folder=None, needed_keys=None):
        self.samples = list(samples)
        self.sub = sub
        self.submission_folder = submission_folder
        # Raw histogram arrays (gt_hist / sub_hist_<folder>) are only kept when a
        # metric actually maps to them: pass the arg_mappings values here. The data
        # is parsed either way to derive the entropies, so this costs no extra I/O —
        # it decides whether hundreds of count arrays are RETAINED per pass.
        self.needed_keys = set(needed_keys or ())
        self._gt = None
        self._sub = None
        self._folders = None

    def wants(self, key):
        return key in self.needed_keys

    # ---- lazily built indexes ----

    def _gt_index(self):
        """({sample_id: [(name, value)]}, {sample_id: gt_entropy}, {sample_id: counts})"""
        if self._gt is not None:
            return self._gt
        _app = _app_module()
        db, CustomField, HistogramData = _app.db, _app.CustomField, _app.HistogramData
        scalars, cf_hist, legacy_hist = {}, {}, {}
        sample_ids = [s.id for s in self.samples]
        for chunk in _chunked(sample_ids):
            rows = db.session.query(
                CustomField.sample_id, CustomField.name, CustomField.field_type,
                CustomField.value_float, CustomField.value_text
            ).filter(CustomField.sample_id.in_(chunk)).order_by(CustomField.id).all()
            for sample_id, name, field_type, value_float, value_text in rows:
                if field_type == 'scalar':
                    scalars.setdefault(sample_id, []).append((name, value_float))
                elif field_type == 'histogram' and name == 'hist' and value_text:
                    cf_hist[sample_id] = value_text
            for sample_id, counts in db.session.query(
                HistogramData.sample_id, HistogramData.counts
            ).filter(HistogramData.sample_id.in_(chunk)).all():
                legacy_hist[sample_id] = counts

        keep = self.wants('gt_hist')
        entropies, hists = {}, {}
        for sample_id, value_text in cf_hist.items():
            try:
                counts = json.loads(value_text)['counts']
                entropies[sample_id] = _entropy_from_counts(counts)
                if keep:
                    hists[sample_id] = np.asarray(counts, dtype=float)
            except Exception:
                entropies[sample_id] = 0.0
        # Sample.histogram_data prefers the legacy table, so it wins here too.
        for sample_id, counts_json in legacy_hist.items():
            try:
                counts = json.loads(counts_json)
                entropies[sample_id] = _entropy_from_counts(counts)
                if keep:
                    hists[sample_id] = np.asarray(counts, dtype=float)
            except Exception:
                entropies[sample_id] = 0.0

        self._gt = (scalars, entropies, hists)
        return self._gt

    def _sub_index(self):
        if self._sub is None:
            self._sub = _submission_field_index(self.sub, [s.name for s in self.samples])
        return self._sub

    def _folder_list(self):
        if self._folders is None:
            self._folders = _hist_folders(self.submission_folder)
        return self._folders

    # ---- per-sample context ----

    def context_for(self, sample):
        context = {}
        scalars, entropies, gt_hists = self._gt_index()

        if sample.id in entropies:
            context['gt_entropy'] = entropies[sample.id]
        if sample.id in gt_hists:
            context['gt_hist'] = gt_hists[sample.id]

        for name, value in scalars.get(sample.id, ()):
            context[f"gt_{name}"] = value
            context[name] = value

        if self.sub:
            by_sample, friendly = self._sub_index()
            for name, value in by_sample.get(sample.name, ()):
                context[f"sub_{name}"] = value
                context[name] = value  # Also store without prefix for direct access
                friendly_name = friendly.get(name)
                if friendly_name:
                    context[friendly_name] = value
                    context[f"sub_{friendly_name}"] = value

            if self.submission_folder:
                for folder_name in self._folder_list():
                    hist_file = os.path.join(self.submission_folder, folder_name, f'{sample.name}.npz')
                    if os.path.exists(hist_file):
                        try:
                            with np.load(hist_file) as data:
                                counts = data['counts']
                                context[f'sub_entropy_{folder_name}'] = _entropy_from_counts(counts)
                                if self.wants(f'sub_hist_{folder_name}'):
                                    context[f'sub_hist_{folder_name}'] = np.asarray(counts, dtype=float)
                        except Exception as e:
                            print(f"DEBUG: Error reading histogram {folder_name} for {sample.name}: {e}")

        return context

    def contexts_for_all(self):
        """Contexts for every sample the builder was constructed with, in order."""
        return [self.context_for(s) for s in self.samples]


def get_metric_context(sample, sub=None, submission_folder=None, needed_keys=None):
    """
    Builds a context dictionary for metric evaluation.
    Includes GT fields and optionally Submission fields for a specific sample.

    submission_folder: Path to the root of the submission contents.

    Single-sample convenience wrapper. When iterating over samples, build one
    MetricContextBuilder for the whole set instead — that is where the batching
    pays off (this wrapper re-queries per call).
    """
    return MetricContextBuilder([sample], sub, submission_folder,
                                needed_keys=needed_keys).context_for(sample)


class GtSourceContextBuilder:
    """
    Batched builder for the gt_* half of a metric context sourced from ANOTHER
    SUBMISSION instead of the dataset ground truth (see
    LeaderboardMetric.gt_source_submission_id).

    Naming mirrors the dataset case so metric code and arg mappings stay identical:
    a submission field "peak" is exposed as "gt_peak", and a histogram folder
    "hist_raw" as "gt_entropy_hist_raw" (plus a plain "gt_entropy" alias when the
    submission has exactly one histogram folder, so metrics wired to the dataset's
    "gt_entropy" keep working when their GT source is switched).

    Same lifetime rule as MetricContextBuilder: one per calculation pass.
    """

    def __init__(self, samples, gt_sub, submission_folder=None, needed_keys=None):
        self.samples = list(samples)
        self.gt_sub = gt_sub
        self.submission_folder = submission_folder
        # Same opt-in as MetricContextBuilder: raw count arrays are only retained
        # when a metric maps to gt_hist / gt_hist_<folder>.
        self.needed_keys = set(needed_keys or ())
        self._fields = None
        self._folders = None

    def wants(self, key):
        return key in self.needed_keys

    def _field_index(self):
        if self._fields is None:
            self._fields = _submission_field_index(self.gt_sub, [s.name for s in self.samples])
        return self._fields

    def _folder_list(self):
        if self._folders is None:
            self._folders = _hist_folders(self.submission_folder)
        return self._folders

    def override_for(self, sample):
        context = {}
        by_sample, friendly = self._field_index()
        for name, value in by_sample.get(sample.name, ()):
            context[f"gt_{name}"] = value
            # Same lm_<id> -> friendly-name shim get_metric_context() applies for sub_*.
            friendly_name = friendly.get(name)
            if friendly_name:
                context[f"gt_{friendly_name}"] = value

        if self.submission_folder:
            hist_entropies, hist_arrays = {}, {}
            for folder_name in self._folder_list():
                hist_file = os.path.join(self.submission_folder, folder_name, f'{sample.name}.npz')
                if not os.path.exists(hist_file):
                    continue
                try:
                    with np.load(hist_file) as data:
                        counts = data['counts']
                        hist_entropies[folder_name] = _entropy_from_counts(counts)
                        if self.wants(f'gt_hist_{folder_name}') or self.wants('gt_hist'):
                            hist_arrays[folder_name] = np.asarray(counts, dtype=float)
                except Exception as e:
                    print(f"DEBUG: Error reading GT-source histogram {folder_name} for {sample.name}: {e}")

            for folder_name, val in hist_entropies.items():
                context[f"gt_entropy_{folder_name}"] = val
            if len(hist_entropies) == 1:
                context['gt_entropy'] = next(iter(hist_entropies.values()))

            for folder_name, arr in hist_arrays.items():
                context[f"gt_hist_{folder_name}"] = arr
            # Same single-folder alias the entropies get, so a metric wired to
            # gt_hist keeps working when its GT source is switched.
            if len(hist_arrays) == 1:
                context['gt_hist'] = next(iter(hist_arrays.values()))

        return context

    def overrides_for_all(self):
        return [self.override_for(s) for s in self.samples]


def build_gt_source_context(sample, gt_sub, submission_folder=None, needed_keys=None):
    """
    Single-sample wrapper around GtSourceContextBuilder. When iterating samples,
    build one GtSourceContextBuilder for the whole set instead.
    """
    return GtSourceContextBuilder([sample], gt_sub, submission_folder,
                                  needed_keys=needed_keys).override_for(sample)


def apply_gt_source(context, gt_override):
    """
    Return a COPY of `context` whose gt_* keys come from `gt_override` only.

    The dataset's gt_* keys are dropped first: if the source submission doesn't
    provide a field the metric asks for, it must read as missing (None) rather
    than silently falling back to the real ground truth.
    """
    merged = {k: v for k, v in context.items() if not k.startswith('gt_')}
    merged.update(gt_override)
    return merged


def sort_metrics_by_dependency(metrics):
    """
    Topologically sorts a list of LeaderboardMetric objects based on dependencies defined in arg_mappings.
    """
    from collections import defaultdict, deque

    # Build graph
    adj = defaultdict(list)
    in_degree = {m.id: 0 for m in metrics}
    metric_map = {m.id: m for m in metrics}
    
    # Map output names to metric IDs for dependency resolution.
    # Metric B depends on A if B uses A's output as an input. A's output is written
    # into the per-sample context under BOTH its displayed name and "lm_<id>", and
    # mappings reference it either way — bare (the "Per-Sample Metric" source in the
    # editor) or prefixed with "sub_" (the "Submission" source, whose field list
    # also offers metric outputs). Every one of those forms needs an ordering edge:
    # without it the dependent metric can run first, and on a FRESH submission the
    # value it needs does not exist yet.
    #
    # gt_* is deliberately excluded: ground truth — and a GT-source submission's
    # stored values — are not produced by this run, so ordering can't help.
    name_to_id = {}
    for m in metrics:
        name = m.target_name if m.target_name else m.global_metric.name
        name_to_id.setdefault(f"sub_{name}", m.id)
        name_to_id.setdefault(f"lm_{m.id}", m.id)
        name_to_id.setdefault(f"sub_lm_{m.id}", m.id)
    # Exact displayed names last so they win over any derived form that collides
    # (e.g. a metric actually named "sub_foo" alongside one named "foo").
    for m in metrics:
        name_to_id[m.target_name if m.target_name else m.global_metric.name] = m.id

    for m in metrics:
        try:
            mappings = json.loads(m.arg_mappings)
            # dependency is a value in mappings
            for dep_name in mappings.values():
                if dep_name in name_to_id:
                    dep_id = name_to_id[dep_name]
                    # If dependency is in the list we are sorting (self-reference or cycle check?)
                    # If dependency is another metric in this list, add edge.
                    if dep_id != m.id:
                        adj[dep_id].append(m.id)
                        in_degree[m.id] += 1
        except:
            pass

    # Kahn's Algorithm
    queue = deque([mid for mid, deg in in_degree.items() if deg == 0])
    sorted_metrics = []

    while queue:
        u_id = queue.popleft()
        sorted_metrics.append(metric_map[u_id])

        for v_id in adj[u_id]:
            in_degree[v_id] -= 1
            if in_degree[v_id] == 0:
                queue.append(v_id)

    # Check for cycles (if len mismatch, cycle exists or disconnected)
    # If cycle, just append remaining arbitrarily? Or prioritize valid ones?
    if len(sorted_metrics) != len(metrics):
        # Add remaining metrics (cycles)
        seen = set(m.id for m in sorted_metrics)
        for m in metrics:
            if m.id not in seen:
                sorted_metrics.append(m)
    
    return sorted_metrics
