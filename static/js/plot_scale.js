/*
 * Symmetric-log ("symlog") Y axis for the scalar X-Y plot, shared by the
 * comparison view's plot panel and the standalone shared-plot page.
 *
 * A true log axis cannot show zero or negative values (Plotly drops them), so
 * when "Log Y" is on and the shown data has any value <= 0, the plot switches
 * to symlog instead:
 *
 *     t = sign(y) * log10(1 + |y| / c)
 *
 * which is linear within about ±c of zero and logarithmic beyond, in both
 * directions. Plotly has no such axis type, so the traces' Y values are
 * transformed and the axis is labelled with the real values (tickvals/ticktext).
 *
 * The transform is reversible: applyToTrace() keeps everything it changes in
 * trace.meta.symlog, so hover text, CSV export and the shared page (which
 * re-renders from the snapshot) can always get the real values back.
 */
(function () {
    function f(y, c) { return Math.sign(y) * Math.log10(1 + Math.abs(y) / c); }
    function inv(t, c) { return Math.sign(t) * c * (Math.pow(10, Math.abs(t)) - 1); }

    // Linear threshold: a power of ten near the small end of the data (5th
    // percentile of the non-zero magnitudes), so small values still separate
    // from zero without wasting decades of empty axis.
    function chooseC(values) {
        const a = values.filter(v => isFinite(v) && v !== 0).map(Math.abs).sort((x, y) => x - y);
        if (!a.length) return 1;
        const p = a[Math.floor((a.length - 1) * 0.05)];
        return Math.pow(10, Math.floor(Math.log10(p)));
    }

    function fmt(v) {
        if (v === 0) return '0';
        const a = Math.abs(v), k = Math.round(Math.log10(a));
        if (Math.abs(a - Math.pow(10, k)) < 1e-9 * a && (k >= 4 || k <= -3)) return (v < 0 ? '−' : '') + '1e' + k;
        return (v < 0 ? '−' : '') + String(+a.toPrecision(3));
    }

    // Ticks at 0 and ±m·10^k, from the threshold's decade up, covering the
    // transformed range [lo, hi]. Decades only (m = 1) when that gives enough
    // ticks; 1-2-5 or every integer multiple when the data spans few decades;
    // every other decade when there would be too many.
    function ticks(lo, hi, c) {
        const reach = Math.max(Math.abs(lo), Math.abs(hi));
        const k0 = Math.floor(Math.log10(c));
        const inRange = (v) => { const t = f(v, c); return t >= lo - 1e-9 && t <= hi + 1e-9; };
        function build(mults, step) {
            const vals = [0];
            for (let k = k0, i = 0; k < k0 + 40; k++, i++) {
                if (f(Math.pow(10, k), c) > reach * 1.0001 && i > 0) break;
                if (i % step) continue;
                mults.forEach(m => { const v = m * Math.pow(10, k); vals.push(v, -v); });
            }
            return vals.filter(inRange).sort((a, b) => a - b);
        }
        let vals = build([1], 1);
        if (vals.length > 13) vals = build([1], 2);
        else if (vals.length < 5) {
            vals = build([1, 2, 5], 1);
            if (vals.length < 5) vals = build([1, 2, 3, 4, 5, 6, 7, 8, 9], 1);
        }
        return { tickvals: vals.map(v => f(v, c)), ticktext: vals.map(fmt) };
    }

    // Replace %{y} in a hovertemplate with the real value, carried per point in
    // customdata (Plotly can't index meta per point).
    function applyToTrace(tr, c) {
        if (!Array.isArray(tr.y) || (tr.meta && tr.meta.symlog)) return;
        const saved = { y: tr.y.slice(), customdata: tr.customdata, hovertemplate: tr.hovertemplate,
                        hoverinfo: tr.hoverinfo, error_y: tr.error_y };
        tr.meta = Object.assign({}, tr.meta, { symlog: saved });
        const orig = saved.y;
        tr.y = orig.map(v => f(v, c));
        if (tr.error_y && Array.isArray(tr.error_y.array)) {
            const sd = tr.error_y.array;
            tr.error_y = Object.assign({}, tr.error_y, {
                symmetric: false,
                array: orig.map((m, i) => f(m + (sd[i] || 0), c) - f(m, c)),
                arrayminus: orig.map((m, i) => f(m, c) - f(m - (sd[i] || 0), c))
            });
        }
        if (typeof tr.hovertemplate === 'string') {
            const cd = Array.isArray(tr.customdata) ? tr.customdata : null;
            if (cd && cd.length && Array.isArray(cd[0])) {
                // [n, trueX, ...] -> append the real y
                const idx = cd[0].length;
                tr.customdata = cd.map((row, i) => row.concat([orig[i]]));
                tr.hovertemplate = tr.hovertemplate.replace(/%\{y\}/g, '%{customdata[' + idx + ']}');
            } else {
                // per-point scalar (tags) or none -> [realY, previous]
                tr.customdata = orig.map((v, i) => [v, cd ? cd[i] : '']);
                tr.hovertemplate = tr.hovertemplate
                    .replace(/%\{customdata\}/g, '%{customdata[1]}')
                    .replace(/%\{y\}/g, '%{customdata[0]}');
            }
        } else {
            // Box traces have no template; their built-in hover would show
            // transformed quartiles, so show only the series name.
            tr.hoverinfo = 'name';
        }
    }

    // A trace as it was before applyToTrace (no-op if it was never transformed).
    function restoreTrace(tr) {
        const s = tr.meta && tr.meta.symlog;
        if (!s) return tr;
        const out = Object.assign({}, tr, { y: s.y, customdata: s.customdata, hovertemplate: s.hovertemplate,
                                           hoverinfo: s.hoverinfo, error_y: s.error_y });
        ['customdata', 'hovertemplate', 'hoverinfo', 'error_y'].forEach(k => { if (out[k] === undefined) delete out[k]; });
        out.meta = Object.assign({}, tr.meta);
        delete out.meta.symlog;
        return out;
    }

    // Real (untransformed) y of a trace, for CSV and the like.
    function realY(tr) { return (tr.meta && tr.meta.symlog) ? tr.meta.symlog.y : tr.y; }
    function realErr(tr) {
        if (tr.meta && tr.meta.symlog) return tr.meta.symlog.error_y;
        return tr.error_y;
    }

    // One size for the legend, axis titles, axis tick numbers and plot title
    // (the title a step larger). Blank / invalid = Plotly's defaults. Margins grow with the font
    // so the bottom legend and axis titles don't collide or clip.
    function applyFontSize(layout, size) {
        size = Number(size);
        if (!isFinite(size) || size <= 0) return layout;
        const k = size / 12;
        const withFont = (t, sz) => {
            const o = (t && typeof t === 'object') ? Object.assign({}, t) : { text: t || '' };
            o.font = Object.assign({}, o.font, { size: sz });
            return o;
        };
        ['xaxis', 'yaxis'].forEach(ax => {
            if (!layout[ax]) layout[ax] = {};
            layout[ax] = Object.assign({}, layout[ax], {
                title: withFont(layout[ax].title, size),
                tickfont: Object.assign({}, layout[ax].tickfont, { size: size }),
                automargin: true
            });
        });
        if (layout.title) layout.title = withFont(layout.title, Math.round(size * 1.3));
        layout.legend = Object.assign({}, layout.legend, { font: Object.assign({}, (layout.legend || {}).font, { size: size }) });
        if (layout.legend.title) layout.legend.title = withFont(layout.legend.title, size);
        // Scale from the unscaled margins, recorded the first time, so applying
        // a size to an already-sized layout (a shared snapshot) doesn't compound.
        const baseMargin = (layout.meta && layout.meta.baseMargin) || layout.margin;
        if (baseMargin) {
            const m = Object.assign({}, baseMargin);
            if (m.b) m.b = Math.round(m.b * Math.max(1, k));
            if (m.t) m.t = Math.round(m.t * Math.max(1, k));
            layout.margin = m;
        }
        layout.meta = Object.assign({}, layout.meta, { fontSize: size, baseMargin: baseMargin });
        return layout;
    }

    window.PlotScale = { applyFontSize: applyFontSize, f: f, inv: inv, chooseC: chooseC, ticks: ticks, fmt: fmt,
                         applyToTrace: applyToTrace, restoreTrace: restoreTrace, realY: realY, realErr: realErr };
})();
