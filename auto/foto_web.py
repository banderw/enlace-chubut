"""Baja fotos candidatas de la web para ilustrar una nota (las revisa Claude antes de elegir una).

Uso:  python3 -X utf8 auto/foto_web.py <url> [<url> ...]
      Cada <url> puede ser una página (se usa su foto principal: og:image / twitter:image)
      o la dirección directa de una imagen (.jpg, .png, .webp).

Guarda cada foto en auto/fotos_candidatas/cand-N.<ext> e imprime: archivo, tamaño en px si se puede, peso y
la URL directa de la imagen (esa es la que va en "foto_url" de la nota).
"""
import os, re, sys, html, urllib.request, urllib.parse

AUTO = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AUTO, "fotos_candidatas")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept-Language": "es-AR,es;q=0.9"}

def bajar(url, limite=8_000_000):
    url = urllib.parse.quote(url, safe=":/?&=%#+,;@~!$'()*[]")  # direcciones con tildes o "°"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read(limite), r.headers.get("Content-Type", "")

WIKI_UA = {"User-Agent": "EnlaceChubutBot/1.0 (https://enlacechubut.com.ar; EnlaceChubut@protonmail.com)"}

def foto_wikipedia(url):
    """Wikipedia bloquea a los navegadores falsos (error 429): se usa su API oficial con un User-Agent propio."""
    m = re.match(r"https?://([a-z]+)\.(?:m\.)?wikipedia\.(?:org|com)/wiki/(.+)$", url)
    titulo = m.group(2) if m else url.rstrip("/").rsplit("/", 1)[-1]
    idiomas = [m.group(1)] if m and m.group(1) not in ("www",) else ["en", "es"]
    import json
    datos, error = None, None
    for idioma in idiomas + [i for i in ("es", "en") if i not in idiomas]:
        try:
            api = f"https://{idioma}.wikipedia.org/api/rest_v1/page/summary/{titulo}"
            with urllib.request.urlopen(urllib.request.Request(api, headers=WIKI_UA), timeout=30) as r:
                datos = json.load(r)
            break
        except Exception as e:
            error = e
    if datos is None:
        raise error
    img = (datos.get("originalimage") or datos.get("thumbnail") or {}).get("source")
    if not img:
        raise ValueError("la página de Wikipedia no tiene foto")
    if "/thumb/" not in img and (datos.get("originalimage") or {}).get("width", 0) > 1600 and datos.get("thumbnail"):
        img = re.sub(r"/\d+px-", "/1280px-", datos["thumbnail"]["source"])
    with urllib.request.urlopen(urllib.request.Request(img, headers=WIKI_UA), timeout=30) as r:
        return img, r.read(8_000_000), r.headers.get("Content-Type", "")

def foto_de_pagina(url):
    if re.search(r"wikipedia\.(org|com)/wiki/", url):
        return foto_wikipedia(url)
    if "upload.wikimedia.org" in url:
        with urllib.request.urlopen(urllib.request.Request(url, headers=WIKI_UA), timeout=30) as r:
            return url, r.read(8_000_000), r.headers.get("Content-Type", "")
    crudo, tipo = bajar(url, 3_000_000)
    if tipo.startswith("image/"):
        return url, crudo, tipo
    pagina = crudo.decode("utf-8", "replace")
    for nombre in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        for tag in re.findall(r"<meta\b[^>]*>", pagina, re.I):
            if re.search(r'(?:property|name)\s*=\s*["\']' + re.escape(nombre) + '["\']', tag, re.I):
                m = re.search(r'content\s*=\s*["\']([^"\']+)', tag, re.I)
                if m:
                    img = urllib.parse.urljoin(url, html.unescape(m.group(1)).strip())
                    datos, t = bajar(img)
                    return img, datos, t
    raise ValueError("la página no tiene foto principal (og:image)")

def medidas(datos):
    try:
        from PIL import Image
        import io
        return "%dx%d" % Image.open(io.BytesIO(datos)).size
    except Exception:
        # JPG sin Pillow: se buscan las medidas en el encabezado SOF
        i = 2
        while datos[:2] == b"\xff\xd8" and i < len(datos) - 9:
            if datos[i] != 0xFF:
                break
            marca, largo = datos[i + 1], int.from_bytes(datos[i + 2:i + 4], "big")
            if marca in (0xC0, 0xC1, 0xC2):
                return "%dx%d" % (int.from_bytes(datos[i + 7:i + 9], "big"), int.from_bytes(datos[i + 5:i + 7], "big"))
            i += 2 + largo
        return "?"

def main():
    os.makedirs(SALIDA, exist_ok=True)
    n = len([f for f in os.listdir(SALIDA) if f.startswith("cand-")])
    for url in sys.argv[1:]:
        try:
            img, datos, tipo = foto_de_pagina(url)
            ext = "png" if "png" in tipo else "webp" if "webp" in tipo else "jpg"
            n += 1
            ruta = os.path.join(SALIDA, f"cand-{n}.{ext}")
            open(ruta, "wb").write(datos)
            print(f"{ruta} | {medidas(datos)} | {len(datos)//1024} KB | foto_url: {img}")
        except Exception as e:
            print(f"[no se pudo] {url}: {e}")

if __name__ == "__main__":
    main()
