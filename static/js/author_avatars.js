/* Git Author Avatar rendering.
 * Renders a small circular avatar with the author's initials and a deterministic
 * color derived from the author name. Used to show "who" uploaded a dataset /
 * submission next to its git info.
 *
 * Exposes a single global: createAuthorAvatar(name, size)
 *   name: the git author name (string)
 *   size: pixel diameter (e.g. 24, 32, 40). Defaults to 32.
 * Returns an HTML string for an .author-avatar element (see author_avatars.css).
 */
(function () {
    // Palette of pleasant, readable background colors.
    const AVATAR_COLORS = [
        '#1abc9c', '#2ecc71', '#3498db', '#9b59b6', '#34495e',
        '#16a085', '#27ae60', '#2980b9', '#8e44ad', '#2c3e50',
        '#f1c40f', '#e67e22', '#e74c3c', '#d35400', '#c0392b',
        '#7f8c8d', '#f39c12', '#e84393', '#6c5ce7', '#00b894'
    ];

    function hashString(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            hash = (hash << 5) - hash + str.charCodeAt(i);
            hash |= 0; // force 32-bit int
        }
        return Math.abs(hash);
    }

    function getInitials(name) {
        if (!name) return '?';
        const parts = name.trim().split(/[\s_\-.]+/).filter(Boolean);
        if (parts.length === 0) return '?';
        if (parts.length === 1) {
            return parts[0].substring(0, 2).toUpperCase();
        }
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    function sizeClass(size) {
        if (size <= 26) return 'author-avatar-small';
        if (size <= 36) return 'author-avatar-medium';
        return 'author-avatar-large';
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    window.createAuthorAvatar = function (name, size) {
        size = size || 32;
        const safeName = name || 'Unknown';
        const color = AVATAR_COLORS[hashString(safeName) % AVATAR_COLORS.length];
        const initials = getInitials(safeName);
        const cls = sizeClass(size);
        // Inline width/height/font-size so explicit sizes (e.g. 24, 40) are honored
        // even if they don't match a CSS class breakpoint exactly.
        const style = `width:${size}px;height:${size}px;font-size:${Math.round(size * 0.42)}px;background-color:${color};`;
        return `<span class="author-avatar ${cls}" style="${style}" title="${escapeHtml(safeName)}">${escapeHtml(initials)}</span>`;
    };
})();
