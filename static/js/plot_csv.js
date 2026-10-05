/*
 * CSV export of a scalar X-Y plot exactly as it is drawn right now. Used by the
 * comparison view's plot panel and by the standalone shared-plot page, so both
 * produce the same file.
 *
 * - Only series that are currently shown are exported (not ones hidden with
 *   Show / Toggle or greyed out in the legend).
 * - Sample-level traces (scatter, line, box) give one row per point:
 *     series, field, submission, sample, <x title>, <y title or "y">
 * - Mean/Std traces give one row per X value:
 *     series, field, <x title>, mean|std, n[, std]
 *   using the TRUE X (the side-by-side offset is display-only) and the bucket
 *   size the tooltip shows.
 *
 * Reads only what the figure carries: trace.meta.series (field), meta.pointSubs
 * (submission id per point), meta.aggKind, and layout.meta.submissionLabels.
 * Figures shared before those existed still export, with blank columns.
 */
(function () {
    function cell(v) {
        v = (v == null ? '' : String(v));
        return /[",\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    }
    function axisTitle(layout, ax, fallback) {
        const t = layout && layout[ax] && layout[ax].title;
        return (t && (typeof t === 'string' ? t : t.text)) || fallback;
    }
    // Real values when the trace was put on a symlog axis (plot_scale.js keeps
    // the originals in meta.symlog).
    function realY(tr) { return (tr.meta && tr.meta.symlog) ? tr.meta.symlog.y : tr.y; }
    function realErr(tr) { return (tr.meta && tr.meta.symlog) ? tr.meta.symlog.error_y : tr.error_y; }
    function isShown(tr) { return tr.visible === undefined || tr.visible === true; }
    // A Mean/Std trace: tagged by the app, or (older shares) recognisable by its
    // [n, trueX] customdata and the absence of per-sample text.
    function aggKindOf(tr) {
        if (tr.meta && tr.meta.aggKind) return tr.meta.aggKind;
        if (!Array.isArray(tr.text) && Array.isArray(tr.customdata) && Array.isArray(tr.customdata[0])) return 'value';
        return null;
    }

    function figureToRows(data, layout) {
        const shown = (data || []).filter(isShown);
        const subLabels = (layout && layout.meta && layout.meta.submissionLabels) || {};
        const fieldOf = (tr) => (tr.meta && tr.meta.series && tr.meta.series.label) || '';
        const xHead = axisTitle(layout, 'xaxis', 'x');
        const fields = new Set(shown.map(fieldOf));
        const yHead = fields.size === 1 ? axisTitle(layout, 'yaxis', 'y') : 'y';
        const aggTraces = shown.filter(aggKindOf);

        if (aggTraces.length) {
            const kind = aggKindOf(aggTraces[0]);
            const withStd = aggTraces.some(tr => { const e = realErr(tr); return e && Array.isArray(e.array); });
            const rows = [['series', 'field', xHead, kind, 'n'].concat(withStd ? ['std'] : [])];
            aggTraces.forEach(tr => {
                (realY(tr) || []).forEach((yv, i) => {
                    const cd = Array.isArray(tr.customdata) ? tr.customdata[i] : null;
                    const n = Array.isArray(cd) ? cd[0] : '';
                    const trueX = Array.isArray(cd) ? cd[1] : (tr.x || [])[i];
                    const row = [tr.name || '', fieldOf(tr), trueX, yv, n];
                    const e = realErr(tr);
                    if (withStd) row.push(e && e.array ? e.array[i] : '');
                    rows.push(row);
                });
            });
            return rows;
        }

        const rows = [['series', 'field', 'submission', 'sample', xHead, yHead]];
        shown.forEach(tr => {
            const subs = tr.meta && tr.meta.pointSubs;
            (tr.x || []).forEach((xv, i) => {
                const sid = subs ? subs[i] : null;
                rows.push([
                    tr.name || '', fieldOf(tr),
                    sid ? (subLabels[sid] || sid) : '',
                    Array.isArray(tr.text) ? (tr.text[i] || '') : '',
                    xv, (realY(tr) || [])[i]
                ]);
            });
        });
        return rows;
    }

    function figureToCsv(data, layout) {
        return figureToRows(data, layout).map(r => r.map(cell).join(',')).join('\r\n');
    }

    function downloadCsv(gd, filename) {
        const text = figureToCsv(gd.data, gd.layout);
        // BOM so Excel opens UTF-8 sample/submission names correctly.
        const blob = new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename || 'plot.csv';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
    }

    window.PlotCsv = { figureToRows: figureToRows, figureToCsv: figureToCsv, downloadCsv: downloadCsv };
})();
