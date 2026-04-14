/* API client helper — safe JSON parsing */
const API = {
    async _parse(resp, method, url) {
        const text = await resp.text();
        try { return JSON.parse(text); }
        catch (e) {
            console.error(`API ${method} ${url} — ${resp.status}: ${text.substring(0, 300)}`);
            return { error: `${resp.status}: ${text.substring(0, 200)}` };
        }
    },
    async get(url) {
        const resp = await fetch(url);
        return this._parse(resp, 'GET', url);
    },
    async post(url, data) {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return this._parse(resp, 'POST', url);
    },
    async put(url, data) {
        const resp = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return this._parse(resp, 'PUT', url);
    },
    async del(url) {
        const resp = await fetch(url, { method: 'DELETE' });
        return this._parse(resp, 'DELETE', url);
    }
};

function toast(msg, type = 'success') {
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

function navHTML() {
    const path = window.location.pathname;
    const links = [
        ['/', 'Dashboard'],
        ['/recorder', 'Flow Builder'],
        ['/transactions', 'Transactions'],
        ['/settings', 'Settings'],
    ];
    return `
        <nav>
            <span class="logo">WA System</span>
            ${links.map(([href, label]) =>
                `<a href="${href}" class="${path === href ? 'active' : ''}">${label}</a>`
            ).join('')}
        </nav>
    `;
}

document.addEventListener('DOMContentLoaded', () => {
    const nav = document.getElementById('nav');
    if (nav) nav.innerHTML = navHTML();
});
