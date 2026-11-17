"""Identidad visual compartida por el sitio del profesor y la página de ingreso.

Colores institucionales de la Pontificia Universidad Javeriana (azul y amarillo) y el
monograma de Fundamentos de Ingeniería de Software. Para usar el escudo oficial basta con
reemplazar `ESCUDO` por el SVG que entregue la universidad.
"""
from __future__ import annotations

UNIVERSIDAD = "Pontificia Universidad Javeriana"
FACULTAD = "Facultad de Ingeniería · Departamento de Ingeniería de Sistemas"
CURSO = "Fundamentos de Ingeniería de Software"
PRODUCTO = "Agente revisor FIS"

# Monograma: escudo estilizado con las siglas del curso (no es el escudo oficial).
ESCUDO = """<svg viewBox="0 0 48 56" width="{t}" height="{a}" aria-hidden="true" class="escudo">
<path d="M24 2 44 9v18c0 13-8.6 22.6-20 27C12.6 49.6 4 40 4 27V9z" fill="var(--jav-azul)" stroke="var(--jav-oro)" stroke-width="2.4"/>
<path d="M24 8 39 13.3v13.4c0 9.6-6.3 16.9-15 20.4-8.7-3.5-15-10.8-15-20.4V13.3z" fill="none" stroke="rgba(255,255,255,.28)" stroke-width="1"/>
<text x="24" y="31.5" text-anchor="middle" font-family="Georgia,'Times New Roman',serif" font-size="13.5" font-weight="700"
 fill="#fff" letter-spacing=".5">FIS</text>
<path d="M14 37h20" stroke="var(--jav-oro)" stroke-width="2" stroke-linecap="round"/></svg>"""


def escudo(alto: int = 40) -> str:
    return ESCUDO.format(t=round(alto * 48 / 56), a=alto)


# Tokens de color: claro y oscuro. Los componentes solo usan estas variables.
TOKENS = """
:root{--jav-azul:#2c5697;--jav-azul-osc:#14305e;--jav-azul-prof:#0c1f40;--jav-oro:#f2b705;--jav-oro-suave:#fff4cc;
--bg:#f3f5f9;--card:#fff;--fg:#14213d;--mut:#5b6679;--bd:#dfe4ec;--acc:#2c5697;--acc2:#f2b705;
--ok:#17794a;--okbg:#e2f4ea;--warn:#8a5a00;--warnbg:#fdf1d3;--bad:#b3261e;--badbg:#fbe4e2;
--s1:#2c5697;--s2:#e0a100;--s3:#2a9d8f;--s4:#c2185b;--s5:#7b5ea7;--s6:#ef6c00;--grid:#e8ecf2;--sombra:0 1px 2px rgba(16,32,64,.06),0 4px 16px rgba(16,32,64,.06)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0b1220;--card:#121b2e;--fg:#e7ecf5;--mut:#9aa6bb;--bd:#24304a;
--acc:#8fb3ff;--ok:#6fd39c;--okbg:#12291e;--warn:#f0c36a;--warnbg:#2c2414;--bad:#ff8a80;--badbg:#311816;
--s1:#8fb3ff;--s2:#f2c94c;--s3:#4fd1c5;--s4:#f48fb1;--s5:#b39ddb;--s6:#ffab40;--grid:#1d2740;--sombra:0 1px 2px rgba(0,0,0,.3)}}
"""
