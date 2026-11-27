"""Busca notas nuevas de Chubut en Diario Jornada, ADNSUR y OPI Santa Cruz.

Uso:  python -I auto/buscar_nuevas.py            -> escribe auto/candidatas.json con las notas que todavía no se vieron
      python -I auto/buscar_nuevas.py --sembrar  -> marca como vistas todas las notas actuales (no genera candidatas)

Una nota "vista" es una URL que ya se usó o se descartó (auto/vistas.json). Este script no modifica el portal.
"""
import json, os, re, sys, html, time, urllib.request
from datetime import datetime, timezone, timedelta

AUTO = os.path.dirname(os.path.abspath(__file__))
VISTAS = os.path.join(AUTO, "vistas.json")
SALIDA = os.path.join(AUTO, "candidatas.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EnlaceChubutBot/1.0", "Accept-Language": "es-AR,es;q=0.9"}
MAX_CANDIDATAS = 15
MAX_POR_MEDIO = 5
MAX_HORAS = 36  # las notas publicadas hace más tiempo se ignoran
LUGARES_CHUBUT = re.compile(r"chubut|rawson|trelew|madryn|comodoro|esquel|trevelin|gaiman|dolavon|sarmiento|rada tilly|"
                            r"camarones|el maitén|el maiten|lago puelo|el hoyo|epuyén|epuyen|cholila|gobernador costa|"
                            r"paso de indios|tecka|gualjaina|corcovado|playa unión|playa union|península valdés|peninsula valdes|"
                            r"puerto pirámides|puerto piramides|ignacio torres|golfo san jorge", re.I)

def bajar(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read().decode("utf-8", "replace")

def limpiar(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()

def enlaces(pagina, base, patron):
    vistos, res = set(), []
    for m in re.finditer(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', pagina, re.S | re.I):
        href, texto = m.group(1), limpiar(m.group(2))
        if href.startswith("/"):
            href = base + href
        href = href.split("?")[0]
        if not re.search(patron, href) or href in vistos:
            continue
        vistos.add(href)
        res.append((href, texto))
    return res

def meta_tag(p, nombre):
    """Lee <meta property|name="nombre" content="..."> sin importar el orden de los atributos."""
    for tag in re.findall(r"<meta\b[^>]*>", p, re.I):
        if re.search(r'(?:property|name)\s*=\s*"' + re.escape(nombre) + '"', tag, re.I):
            c = re.search(r'content\s*=\s*"([^"]*)"', tag, re.I)
            if c:
                return html.unescape(c.group(1)).strip()
    return ""

def leer_nota(url):
    crudo = bajar(url)
    p = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", crudo, flags=re.S | re.I)
    t = meta_tag(p, "og:title") or limpiar((re.search(r"<title>(.*?)</title>", p, re.S | re.I) or [None, ""])[1])
    titulo = re.sub(r"\s*[-|—]\s*(ADNSUR|OPI Santa Cruz|Diario Jornada).*$", "", t)
    copete = meta_tag(p, "description") or meta_tag(p, "og:description")
    vistos, parrafos = set(), []
    for m in re.finditer(r"<p(?:\s[^>]*)?>(.*?)</p>", p, re.S | re.I):
        t = limpiar(m.group(1))
        if len(t) > 70 and t not in vistos and not re.search(r"cookies|suscrib|whatsapp|copyright|todos los derechos", t, re.I):
            vistos.add(t)
            parrafos.append(t)
    fecha = None
    m = re.search(r'(?:article:published_time"\s+content|"datePublished"\s*:\s*)"?([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{5,8}(?:\.\d+)?(?:Z|[+-][0-9:]{4,5})?)', crudo)
    if not m:
        pub = meta_tag(crudo, "article:published_time")
        m = re.match(r"(.+)", pub) if pub else None
    if m:
        try:
            fecha = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=timezone(timedelta(hours=-3)))
        except ValueError:
            fecha = None
    return (titulo, copete, " ".join(parrafos)[:2600], fecha)

FUENTES = [
    ("Diario Jornada", "https://www.diariojornada.com.ar/home", "https://www.diariojornada.com.ar", r"diariojornada\.com\.ar/\d{6}/[a-z]+/"),
    ("ADNSUR", "https://www.adnsur.com.ar/", "https://www.adnsur.com.ar", r"adnsur\.com\.ar/.+_a[0-9a-f]{20,}$"),
    ("OPI Santa Cruz", "https://www.opisantacruz.com.ar/", "https://www.opisantacruz.com.ar", r"opisantacruz\.com\.ar/20\d\d/\d\d/\d\d/[^/]+/?$"),
]

GOB_API = "https://noticias.chubut.gob.ar/api/posts/?page={}"
GOB_BASE = "https://noticias.chubut.gob.ar"
GOBERNADOR = re.compile(r"\b(Ignacio|Nacho)\s+(“?Nacho”?\s+)?Torres\b|\bgobernador\s+Torres\b|\bTorres\b", re.I)
GACETILLAS_POR_DIA = 2   # el usuario quiere solo las 2 más importantes de cada día
MAX_GACETILLAS = 8       # candidatas para elegir

NACIONALES_POR_DIA = 2   # sección "Nacionales": solo las 2 noticias del país más importantes de cada día

def _hechas_hoy(condicion, maximo):
    hoy = datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
    try:
        notas = json.load(open(os.path.join(os.path.dirname(AUTO), "data", "notas.json"), encoding="utf-8"))["notas"]
    except Exception:
        return maximo
    hechas = sum(1 for n in notas if condicion(n) and str(n.get("fecha", "")).startswith(hoy))
    return max(0, maximo - hechas)

def cupo_gacetillas():
    """Cuántas gacetillas se pueden publicar todavía hoy (notas con la marca 'gacetilla' y fecha de hoy)."""
    return _hechas_hoy(lambda n: n.get("gacetilla") or n.get("sec") == "gobierno", GACETILLAS_POR_DIA)

def cupo_nacionales():
    """Cuántas notas de la sección 'nacionales' se pueden publicar todavía hoy."""
    return _hechas_hoy(lambda n: n.get("sec") == "nacionales", NACIONALES_POR_DIA)

def gacetillas(vistas):
    """Gacetillas oficiales del Gobierno del Chubut (API de noticias.chubut.gob.ar), solo de hoy y ayer."""
    if cupo_gacetillas() == 0:
        return []
    hoy = datetime.now(timezone(timedelta(hours=-3))).date()
    validas = {hoy.strftime("%d.%m.%Y"), (hoy - timedelta(days=1)).strftime("%d.%m.%Y")}
    res = []
    for pagina in (1, 2, 3):
        try:
            items = json.loads(bajar(GOB_API.format(pagina)))["data"]["data"]
        except Exception as e:
            print(f"[aviso] no se pudo leer las gacetillas del Gobierno: {e}")
            break
        viejas = 0
        for it in items:
            clave = f"{GOB_BASE}/gacetilla/{it['id']}"
            if it.get("fecha_alt") not in validas:
                viejas += 1
                continue
            if clave in vistas or len(res) >= MAX_GACETILLAS:
                continue
            texto = limpiar(re.sub(r"<h2.*?</h2>", " ", it.get("content") or "", flags=re.S))
            # El usuario quiere solo gacetillas donde aparece el gobernador Ignacio Torres
            if not GOBERNADOR.search(f"{it.get('title') or ''} {texto}"):
                vistas.add(clave)
                continue
            img = it.get("image") or ""
            res.append({"url": clave, "medio": "Gobierno del Chubut (gacetilla oficial)", "gacetilla": True,
                        "categoria": it.get("category_name"), "titulo": html.unescape(it.get("title") or ""),
                        "copete": "", "publicada": it.get("fecha_alt"), "texto": texto[:3200],
                        "foto_url": (GOB_BASE + img.replace(" ", "%20")) if img.startswith("/") else img,
                        "menciona_chubut": True})
        if viejas == len(items) or len(res) >= MAX_GACETILLAS:
            break
    return res

def main():
    # Traba: si otra actualización empezó hace menos de 20 minutos, no se hace nada (evita notas duplicadas)
    traba = os.path.join(AUTO, ".actualizando")
    if "--sembrar" not in sys.argv:
        if os.path.exists(traba) and time.time() - os.path.getmtime(traba) < 20 * 60:
            print("0 candidatas nuevas (hay otra actualización en curso)")
            return
        open(traba, "w").close()
    vistas = set(json.load(open(VISTAS, encoding="utf-8"))) if os.path.exists(VISTAS) else set()
    sembrar = "--sembrar" in sys.argv
    todas = []
    for medio, url, base, patron in FUENTES:
        try:
            for href, texto in enlaces(bajar(url), base, patron):
                todas.append((medio, href, texto))
        except Exception as e:
            print(f"[aviso] no se pudo leer {medio}: {e}")
    if sembrar:
        vistas.update(h for _, h, _ in todas)
        json.dump(sorted(vistas), open(VISTAS, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        print(f"Sembradas {len(vistas)} URL como vistas.")
        return
    candidatas, por_medio = [], {}
    for medio, href, texto in todas:
        if href in vistas or len(candidatas) >= MAX_CANDIDATAS or por_medio.get(medio, 0) >= MAX_POR_MEDIO:
            continue
        try:
            titulo, copete, cuerpo, fecha = leer_nota(href)
            time.sleep(2)
        except Exception as e:
            print(f"[aviso] no se pudo leer {href}: {e}")
            continue
        if fecha and datetime.now(timezone.utc) - fecha > timedelta(hours=MAX_HORAS):
            vistas.add(href)  # nota vieja: no se vuelve a revisar
            continue
        texto_total = f"{titulo} {copete} {cuerpo}"
        # OPI es de Santa Cruz: solo pasan las notas que mencionan Chubut. Jornada y ADNSUR también publican notas nacionales:
        # se marcan para que Claude decida.
        chubut = bool(LUGARES_CHUBUT.search(texto_total))
        if medio == "OPI Santa Cruz" and not chubut:
            vistas.add(href)
            continue
        por_medio[medio] = por_medio.get(medio, 0) + 1
        candidatas.append({"url": href, "medio": medio, "titulo": titulo or texto, "copete": copete,
                           "publicada": fecha.isoformat() if fecha else None, "texto": cuerpo, "menciona_chubut": chubut})
    candidatas += gacetillas(vistas)
    json.dump(sorted(vistas), open(VISTAS, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    ahora = datetime.now(timezone(timedelta(hours=-3))).isoformat(timespec="seconds")
    json.dump({"generado": ahora, "cupo_gacetillas_hoy": cupo_gacetillas(), "cupo_nacionales_hoy": cupo_nacionales(), "candidatas": candidatas},
              open(SALIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(candidatas)} candidatas nuevas -> {SALIDA}")
    for c in candidatas:
        print(f"- [{c['medio']}] {'CHUBUT ' if c['menciona_chubut'] else ''}{c['titulo'][:110]}")

if __name__ == "__main__":
    main()
