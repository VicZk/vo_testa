/* ========== Scroll Reveal ========== */
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
        }
    });
}, { threshold: 0.1 });

document.querySelectorAll('.fade-section').forEach(el => observer.observe(el));

/* ========== Menu Mobile ========== */
const menuBtn = document.getElementById('menuBtn');
const mobileMenu = document.getElementById('mobileMenu');
const menuOverlay = document.getElementById('menuOverlay');
const menuIcon = document.getElementById('menuIcon');
const closeIcon = document.getElementById('closeIcon');
let menuOpen = false;

function toggleMenu() {
    menuOpen = !menuOpen;
    mobileMenu.classList.toggle('open', menuOpen);
    menuOverlay.classList.toggle('open', menuOpen);
    menuIcon.classList.toggle('hidden', menuOpen);
    closeIcon.classList.toggle('hidden', !menuOpen);
    document.body.style.overflow = menuOpen ? 'hidden' : '';
    // Aberta, a gaveta é um diálogo: o aviso de cookies e os botões flutuantes
    // saem da frente (regra no animations.css). Sem isto, o aviso (z-index 90)
    // cobria o "Fazer Reserva" do fim da gaveta.
    document.documentElement.classList.toggle('menu-do-site-aberto', menuOpen);
    // O botão dizia "Abrir menu" mesmo com o menu aberto.
    menuBtn.setAttribute('aria-expanded', menuOpen ? 'true' : 'false');
    menuBtn.setAttribute('aria-label', menuOpen ? 'Fechar menu' : 'Abrir menu');
    // Aberto, o menu cobre a tela: o foco vai para dentro dele e, ao fechar,
    // volta para o botão — ninguém perde o lugar.
    if (menuOpen) {
        const primeiro = mobileMenu.querySelector('a[href], button:not([disabled])');
        if (primeiro) primeiro.focus();
    } else if (mobileMenu.contains(document.activeElement)) {
        menuBtn.focus();
    }
}

if (menuBtn) {
    menuBtn.addEventListener('click', toggleMenu);
    menuOverlay.addEventListener('click', toggleMenu);

    document.querySelectorAll('.mobile-link').forEach(link => {
        link.addEventListener('click', () => {
            if (menuOpen) toggleMenu();
        });
    });

    // Enquanto o menu está aberto ele é um diálogo: Esc fecha e o Tab circula
    // dentro dele (antes o foco escapava para a página atrás do véu).
    document.addEventListener('keydown', e => {
        if (!menuOpen) return;
        if (e.key === 'Escape') { toggleMenu(); return; }
        if (e.key !== 'Tab') return;
        const itens = Array.from(
            mobileMenu.querySelectorAll('a[href], button:not([disabled])'));
        if (!itens.length) return;
        const primeiro = itens[0], ultimo = itens[itens.length - 1];
        const dentro = mobileMenu.contains(document.activeElement);
        if (e.shiftKey && (!dentro || document.activeElement === primeiro)) {
            e.preventDefault(); ultimo.focus();
        } else if (!e.shiftKey && (!dentro || document.activeElement === ultimo)) {
            e.preventDefault(); primeiro.focus();
        }
    });
}

/* Âncoras do menu: topo do alvo alinhado à base do header (todas iguais) */
const headerEl = document.querySelector('header');
const ANCORAS_MENU = new Set([
    '#inicio',
    '#sobre',
    '#quartos',
    '#dia-pousada',
    '#eventos',
    '#experiencias',
    '#galeria',
    '#contato',
]);

function headerOffset() {
    return headerEl ? Math.ceil(headerEl.getBoundingClientRect().height) : 0;
}

function syncHeaderOffset() {
    document.documentElement.style.setProperty('--header-offset', `${headerOffset()}px`);
}
syncHeaderOffset();
window.addEventListener('resize', syncHeaderOffset);

function hashDeHref(href) {
    if (!href || !href.includes('#')) return '';
    return '#' + href.split('#')[1].split(/[?&]/)[0];
}

function revelarAncora(el) {
    el.querySelectorAll('.fade-section').forEach(s => s.classList.add('visible'));
    if (el.classList.contains('fade-section')) el.classList.add('visible');
}

function yAlvoAncora(el) {
    /* Mede depois do fade (sem translateY) para todas as seções caírem na mesma linha */
    return Math.round(el.getBoundingClientRect().top + window.scrollY - headerOffset());
}

function scrollNaDivisa(hash, { smooth = true } = {}) {
    if (!ANCORAS_MENU.has(hash)) return;
    if (hash === '#inicio') {
        window.scrollTo({ top: 0, behavior: smooth ? 'smooth' : 'auto' });
        return;
    }
    const el = document.querySelector(hash);
    if (!el) return;
    revelarAncora(el);
    syncHeaderOffset();
    void el.offsetHeight; /* reflow após tirar translateY do fade */
    const top = Math.max(0, yAlvoAncora(el));
    window.scrollTo({ top, behavior: smooth ? 'smooth' : 'auto' });

    const corrigir = () => {
        syncHeaderOffset();
        const ajuste = Math.max(0, yAlvoAncora(el));
        if (Math.abs(ajuste - window.scrollY) > 3) {
            window.scrollTo({ top: ajuste, behavior: 'auto' });
        }
    };
    if (smooth) {
        window.addEventListener('scrollend', corrigir, { once: true });
        setTimeout(corrigir, 450); /* fallback se não houver scrollend */
    } else {
        requestAnimationFrame(corrigir);
    }
}

function linkMesmaPagina(a, href) {
    if (href.startsWith('#')) return true;
    try {
        return new URL(a.href, location.origin).pathname === location.pathname;
    } catch (_) {
        return false;
    }
}

if (ANCORAS_MENU.has(location.hash)) {
    window.addEventListener('load', () => {
        syncHeaderOffset();
        scrollNaDivisa(location.hash, { smooth: false });
    });
}

document.querySelectorAll('a[href*="#"]').forEach(a => {
    a.addEventListener('click', (ev) => {
        const href = a.getAttribute('href') || '';
        const hash = hashDeHref(href);
        if (!ANCORAS_MENU.has(hash)) return;
        if (!linkMesmaPagina(a, href)) return;
        if (hash !== '#inicio' && !document.querySelector(hash)) return;
        ev.preventDefault();
        history.pushState(null, '', hash);
        syncHeaderOffset();
        scrollNaDivisa(hash);
    });
});

/* ========== Máscaras CPF / telefone (WhatsApp) ========== */
function soDigitos(v) {
    return String(v || '').replace(/\D/g, '');
}

function mascaraCpf(v) {
    const d = soDigitos(v).slice(0, 11);
    return d
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d{1,2})$/, '$1-$2');
}

function mascaraTelefone(v) {
    const d = soDigitos(v).slice(0, 11);
    if (d.length <= 10) {
        return d
            .replace(/(\d{2})(\d)/, '($1) $2')
            .replace(/(\d{4})(\d)/, '$1-$2');
    }
    return d
        .replace(/(\d{2})(\d)/, '($1) $2')
        .replace(/(\d{5})(\d)/, '$1-$2');
}

function aplicarMascara(el) {
    const tipo = el.getAttribute('data-mask');
    const fmt = tipo === 'cpf' ? mascaraCpf : tipo === 'telefone' ? mascaraTelefone : null;
    if (!fmt) return;
    const sync = () => {
        const pos = el.selectionStart;
        const antes = el.value.length;
        el.value = fmt(el.value);
        const depois = el.value.length;
        if (document.activeElement === el && typeof pos === 'number') {
            const nova = Math.max(0, pos + (depois - antes));
            try { el.setSelectionRange(nova, nova); } catch (_) { /* ignore */ }
        }
    };
    el.addEventListener('input', sync);
    el.addEventListener('blur', sync);
    if (el.value) sync();
}

document.querySelectorAll('[data-mask="cpf"], [data-mask="telefone"]').forEach(aplicarMascara);


/* ── Galeria: lightbox/carrossel (foto grande + cartão + Instagram) ── */
(function () {
    const lb = document.getElementById('galeria-lightbox');
    const grid = document.getElementById('galeria-grid');
    if (!lb || !grid) return;

    const botoes = Array.from(grid.querySelectorAll('[data-galeria-item]')).filter(b => b.dataset.src);
    const itens = botoes.map(b => ({ src: b.dataset.src, legenda: b.dataset.legenda, categoria: b.dataset.categoria }));
    if (!itens.length) return;

    const insta = lb.dataset.instagram || '#';
    const q = s => lb.querySelector(s);
    let atual = 0;
    let origem = null;
    let overflowAnterior = '';

    function pintar() {
        const f = itens[atual];
        q('[data-gl-img]').src = f.src;
        q('[data-gl-img]').alt = f.legenda || f.categoria;
        q('[data-gl-legenda]').textContent = f.legenda || f.categoria;
        q('[data-gl-categoria]').textContent = f.categoria;
        q('[data-gl-insta]').href = insta;
        q('[data-gl-contador]').textContent = `${atual + 1} / ${itens.length}`;
    }

    function ir(i) { atual = (i + itens.length) % itens.length; pintar(); }

    function abrir(i) {
        origem = botoes[i];
        overflowAnterior = document.body.style.overflow;
        ir(i);
        lb.showModal();
        document.body.style.overflow = 'hidden';
    }
    function fechar() { lb.close(); }
    lb.addEventListener('close', () => {
        document.body.style.overflow = overflowAnterior;
        origem?.focus({ preventScroll: true });
    });

    botoes.forEach((b, i) => b.addEventListener('click', () => abrir(i)));
    q('[data-gl-prev]')?.addEventListener('click', () => ir(atual - 1));
    q('[data-gl-next]')?.addEventListener('click', () => ir(atual + 1));
    q('[data-gl-close]')?.addEventListener('click', fechar);
    lb.addEventListener('click', e => { if (e.target === lb) fechar(); });
    lb.addEventListener('keydown', e => {
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
            e.preventDefault();
            ir(atual + (e.key === 'ArrowLeft' ? -1 : 1));
        }
    });
})();
