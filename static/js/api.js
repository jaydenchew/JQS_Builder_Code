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
            <span class="nav-spacer"></span>
            <div class="nav-svc" id="nav-svc" title="Loading services…">
                <span class="nav-svc-dot loading"></span>
                <span class="nav-svc-text">Services</span>
            </div>
            <div class="nav-svc-pop" id="nav-svc-pop"></div>
        </nav>
    `;
}

const SVC_LABELS = {
    mysql: 'MySQL',
    arm_wcf: 'Arm WCF',
    cloudflare_tunnel: 'Tunnel',
    wa_service: 'WA Service',
};

async function loadNavServices() {
    const wrap = document.getElementById('nav-svc');
    const pop = document.getElementById('nav-svc-pop');
    if (!wrap || !pop) return;
    let data;
    try { data = await API.get('/api/monitor/services'); }
    catch (e) { data = null; }
    if (!data || data.error) {
        wrap.innerHTML = '<span class="nav-svc-dot off"></span><span class="nav-svc-text">Services</span>';
        wrap.title = 'Service check unavailable';
        pop.innerHTML = '<div class="nav-svc-pop-row" style="color:var(--danger)">Service check unavailable</div>';
        return;
    }
    const entries = Object.entries(data);
    const allOnline = entries.every(([, s]) => s.online);
    const offCount = entries.filter(([, s]) => !s.online).length;
    const summaryDot = allOnline ? 'on' : 'off';
    const summaryTxt = allOnline ? 'Services' : `Services (${offCount} down)`;
    wrap.innerHTML = `<span class="nav-svc-dot ${summaryDot}"></span><span class="nav-svc-text">${summaryTxt}</span>`;
    wrap.title = entries.map(([k, s]) => `${SVC_LABELS[k] || k}: ${s.online ? 'OK' : 'DOWN'} (${s.detail})`).join('\n');
    pop.innerHTML = entries.map(([k, s]) => `
        <div class="nav-svc-pop-row">
            <span class="nav-svc-dot ${s.online ? 'on' : 'off'}"></span>
            <span class="nav-svc-pop-name">${SVC_LABELS[k] || k}</span>
            <span class="nav-svc-pop-detail">${s.detail}</span>
        </div>
    `).join('');
}

function _bindNavSvcToggle() {
    const wrap = document.getElementById('nav-svc');
    const pop = document.getElementById('nav-svc-pop');
    if (!wrap || !pop) return;
    wrap.addEventListener('click', (e) => {
        e.stopPropagation();
        pop.classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
        if (!pop.contains(e.target) && e.target !== wrap) pop.classList.remove('open');
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const nav = document.getElementById('nav');
    if (nav) {
        nav.innerHTML = navHTML();
        _bindNavSvcToggle();
        loadNavServices();
        setInterval(loadNavServices, 30000);
    }
});
