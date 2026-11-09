/*
 * Point-click menu for the scalar X-Y plot, shared by the comparison view's
 * plot panel and the standalone shared-plot page.
 *
 * Clicking a sample point offers two ways to open the comparison, both
 * filtered to that sample:
 *   - only the clicked point's submission
 *   - every submission currently shown in the graph
 * When the two would be the same (one submission plotted, or a point that
 * belongs to no submission) it opens straight away, without the menu.
 *
 * Reads what the figure carries: trace.meta.pointSubs (submission id per
 * point; Mean/Std traces keep theirs in meta.raw.sub).
 */
(function () {
    function isShown(tr) { return tr.visible === undefined || tr.visible === true; }

    // The submission the clicked point belongs to, or null.
    function pointSubmission(gd, p) {
        const tr = gd.data && gd.data[p.curveNumber];
        const subs = tr && tr.meta && tr.meta.pointSubs;
        const i = Array.isArray(p.pointIndex) ? p.pointIndex[0] : p.pointIndex;
        return (subs && i != null && subs[i]) ? String(subs[i]) : null;
    }

    // Every submission with a point in a shown series, in id order.
    function graphSubmissions(gd) {
        const ids = new Set();
        (gd.data || []).filter(isShown).forEach(tr => {
            const m = tr.meta || {};
            const subs = m.pointSubs || (m.raw && m.raw.sub) || [];
            subs.forEach(s => { if (s != null && s !== '') ids.add(String(s)); });
        });
        return Array.from(ids).sort((a, b) => Number(a) - Number(b));
    }

    let openMenuEl = null;
    function closeMenu() {
        if (openMenuEl) { openMenuEl.remove(); openMenuEl = null; }
        document.removeEventListener('mousedown', onOutside, true);
        document.removeEventListener('keydown', onKey, true);
    }
    function onOutside(e) { if (openMenuEl && !openMenuEl.contains(e.target)) closeMenu(); }
    function onKey(e) { if (e.key === 'Escape') closeMenu(); }

    function open(url) { window.open(url, '_blank', 'noopener'); }

    /*
     * opts:
     *   gd         the plot div
     *   point      Plotly's clicked point (ev.points[0])
     *   event      the mouse event (ev.event), for placing the menu
     *   urlFor     ids => URL string; ids is an array of submission ids, or
     *              null to keep the comparison's own submission list
     *   labelFor   id => display name of a submission
     */
    function handleClick(opts) {
        const p = opts.point;
        if (!p || !p.text) return;
        const subId = pointSubmission(opts.gd, p);
        const all = graphSubmissions(opts.gd);
        const choices = [];
        if (subId) choices.push({ label: 'Only ' + (opts.labelFor(subId) || ('submission ' + subId)), url: opts.urlFor([subId]) });
        const allDiffers = !subId || all.length > 1 || (all.length === 1 && all[0] !== subId);
        if (allDiffers) {
            choices.push({
                label: all.length ? 'All ' + all.length + ' submission' + (all.length === 1 ? '' : 's') + ' in the graph'
                                  : 'The full comparison',
                url: opts.urlFor(all.length ? all : null)
            });
        }
        if (choices.length === 1) { open(choices[0].url); return; }

        closeMenu();
        // The point's hover box would sit on top of the menu.
        try { if (window.Plotly && Plotly.Fx) Plotly.Fx.unhover(opts.gd); } catch (e) { }
        const menu = document.createElement('div');
        menu.setAttribute('role', 'menu');
        // Above Bootstrap modals (z-index 1055), since the app's plot is in one.
        menu.style.cssText = 'position:fixed;z-index:3000;background:#fff;color:#212529;border:1px solid rgba(0,0,0,.18);'
            + 'border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,.18);padding:4px 0;min-width:220px;'
            + 'font:13px system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;';
        const head = document.createElement('div');
        head.textContent = 'Open comparison for ' + p.text;
        head.style.cssText = 'padding:4px 12px 6px;color:#6c757d;font-size:12px;border-bottom:1px solid #eee;margin-bottom:2px;';
        menu.appendChild(head);
        choices.forEach(c => {
            const item = document.createElement('button');
            item.type = 'button';
            item.setAttribute('role', 'menuitem');
            item.textContent = c.label + ' ↗';
            item.style.cssText = 'display:block;width:100%;text-align:left;border:0;background:none;padding:6px 12px;cursor:pointer;font:inherit;color:inherit;';
            item.addEventListener('mouseenter', () => { item.style.background = '#f1f3f5'; });
            item.addEventListener('mouseleave', () => { item.style.background = 'none'; });
            item.addEventListener('click', () => { closeMenu(); open(c.url); });
            menu.appendChild(item);
        });
        document.body.appendChild(menu);
        openMenuEl = menu;
        // Next to the click, kept inside the window.
        const e = opts.event || {};
        const x = (e.clientX != null ? e.clientX : window.innerWidth / 2) + 8;
        const y = (e.clientY != null ? e.clientY : window.innerHeight / 2) + 8;
        const r = menu.getBoundingClientRect();
        menu.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 4)) + 'px';
        menu.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 4)) + 'px';
        setTimeout(() => {
            document.addEventListener('mousedown', onOutside, true);
            document.addEventListener('keydown', onKey, true);
        }, 0);
    }

    window.PlotClick = { handleClick: handleClick, pointSubmission: pointSubmission,
                         graphSubmissions: graphSubmissions, closeMenu: closeMenu };
})();
