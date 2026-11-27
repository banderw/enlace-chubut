"""Agrega al portal las notas escritas en auto/nuevas.json y marca las URL usadas o descartadas como vistas.

Formato de auto/nuevas.json:
{
  "notas": [
    {"id": "slug-unico", "sec": "ultimas|politica|nacionales|cuenca|turismo|policiales|deportes", "gacetilla": true (solo gacetillas),
     "ciudad": "Trelew", "tema": "etiqueta corta para la barra de Temas", "titulo": "...", "bajada": "...", "cuerpo": ["párrafo 1", "párrafo 2", ...],
     "foto": "nombre-en-banco-fotos (sin .jpg) o null", "arte": "ilustración de respaldo",
     "lugar": "lead | lado (opcional, solo para la nota más importante)", "origen": "URL de la nota original"}
  ],
  "descartadas": ["URL que no se publican (no son de Chubut, repetidas, etc.)"]
}

Uso: python -I auto/agregar_notas.py   (después se publica con publicar.ps1)
"""
import json, os, re, shutil, sys
from datetime import datetime, timezone, timedelta

AUTO = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(AUTO)
DATOS = os.path.join(BASE, "data", "notas.json")
FOTOS = os.path.join(BASE, "fotos")
BANCO = os.path.join(BASE, "banco-fotos")
VISTAS = os.path.join(AUTO, "vistas.json")
ENTRADA = os.path.join(AUTO, "nuevas.json")
REGISTRO = os.path.join(AUTO, "registro.log")
USO = os.path.join(AUTO, "uso_fotos.json")
MAX_NOTAS = 90
ARTES = {"meseta", "valle", "mar", "playa", "cordillera", "ciudad", "petroleo", "tren", "puma", "ruta", "escenario",
         "escuela", "banco", "molino", "faro", "noche", "humo", "cancha", "rugby", "eclipse"}

def bajar_foto(url, destino):
    """Baja la foto oficial de una gacetilla, la achica a 1280 px y la guarda como JPG. Devuelve True si salió bien."""
    try:
        import io, urllib.request
        ua = ("EnlaceChubutBot/1.0 (https://enlacechubut.com.ar; EnlaceChubut@protonmail.com)" if "wikimedia.org" in url else
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
        import urllib.parse
        url = urllib.parse.quote(url, safe=":/?&=%#+,;@~!$'()*[]")  # direcciones con tildes o "°"
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        raw = urllib.request.urlopen(req, timeout=40).read()
        try:
            from PIL import Image
        except Exception:
            # Sin Pillow (pasa en la nube): se guarda el archivo tal cual si es un JPG de tamaño razonable
            # JPG, PNG o WEBP: los navegadores los muestran bien aunque el archivo se llame .jpg
            es_imagen = raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n" or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
            if es_imagen and len(raw) < 3_000_000:
                open(destino, "wb").write(raw)
                return True
            raise
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im.thumbnail((1280, 1280))
        im.save(destino, quality=80, optimize=True, progressive=True)
        return True
    except Exception as e:
        print(f"[aviso] no se pudo bajar la foto {url}: {e}")
        return False

def falla(msg):
    print("ERROR:", msg)
    sys.exit(1)

def main():
    if not os.path.exists(ENTRADA):
        falla("no existe auto/nuevas.json")
    entrada = json.load(open(ENTRADA, encoding="utf-8-sig"))  # acepta el archivo con o sin BOM
    datos = json.load(open(DATOS, encoding="utf-8"))
    secciones = {s["id"] for s in datos["secciones"]}
    ids = {n["id"] for n in datos["notas"]}
    ahora = datetime.now(timezone(timedelta(hours=-3)))
    vistas = set(json.load(open(VISTAS, encoding="utf-8"))) if os.path.exists(VISTAS) else set()
    uso = json.load(open(USO, encoding="utf-8")) if os.path.exists(USO) else {}

    agregadas = []
    for i, n in enumerate(entrada.get("notas", [])):
        # Validación
        for campo in ("id", "sec", "titulo", "bajada", "cuerpo"):
            if not n.get(campo):
                falla(f"la nota {i} no tiene '{campo}'")
        if n["sec"] not in secciones:
            falla(f"sección inválida '{n['sec']}' (válidas: {sorted(secciones)})")
        cuerpo = [p.strip() for p in n["cuerpo"] if str(p).strip()]
        if not 2 <= len(cuerpo) <= 6:
            falla(f"la nota '{n['id']}' debe tener entre 2 y 6 párrafos")
        nid = re.sub(r"[^a-z0-9-]+", "-", n["id"].lower()).strip("-")[:60] or f"nota-{ahora:%H%M}"
        base_id, k = nid, 2
        while nid in ids:
            nid, k = f"{base_id}-{k}", k + 1
        arte = n.get("arte") if n.get("arte") in ARTES else "meseta"
        nota = {"id": nid, "fecha": (ahora + timedelta(seconds=i)).isoformat(timespec="seconds"), "sec": n["sec"],
                "ciudad": n.get("ciudad", "").strip(), "titulo": n["titulo"].strip(), "bajada": n["bajada"].strip(),
                "cuerpo": cuerpo, "arte": arte}
        if n.get("gacetilla"):
            nota["gacetilla"] = True  # sirve para el cupo diario de gacetillas; no se muestra en el portal
        tema = str(n.get("tema") or "").strip()
        if tema:
            nota["tema"] = tema[:28]
        # Foto: se copia del banco con el nombre de la nota. Si viene un tema ("policia"), se usa la variante menos usada.
        foto = n.get("foto")
        foto_url = n.get("foto_url")
        foto_archivo = n.get("foto_archivo")  # foto ya bajada y revisada con auto/foto_web.py
        ruta_archivo = os.path.normpath(os.path.join(BASE, foto_archivo)) if foto_archivo else None
        if ruta_archivo and ruta_archivo.startswith(os.path.join(AUTO, "fotos_candidatas")) and os.path.exists(ruta_archivo) \
                and os.path.getsize(ruta_archivo) < 3_000_000:
            shutil.copyfile(ruta_archivo, os.path.join(FOTOS, nid + ".jpg"))
            foto = None
        elif foto_url and bajar_foto(foto_url, os.path.join(FOTOS, nid + ".jpg")):
            foto = None  # se usó la foto oficial de la gacetilla
        elif foto_url and not foto:
            foto = "gobierno"
        if foto:
            if not os.path.exists(os.path.join(BANCO, foto + ".jpg")):
                variantes = sorted(f[:-4] for f in os.listdir(BANCO) if re.fullmatch(re.escape(foto) + r"-\d+\.jpg", f))
                if not variantes:
                    falla(f"no existe banco-fotos/{foto}.jpg ni el tema '{foto}' (ver banco-fotos/indice.json)")
                foto = min(variantes, key=lambda v: (uso.get(v, 0), v))
            uso[foto] = uso.get(foto, 0) + 1
            shutil.copyfile(os.path.join(BANCO, foto + ".jpg"), os.path.join(FOTOS, nid + ".jpg"))
        elif not os.path.exists(os.path.join(FOTOS, nid + ".jpg")):
            nota["sinFoto"] = True
        # Lugar en la portada
        lugar = n.get("lugar")
        if lugar == "lead":
            for v in datos["notas"]:
                if v.get("lugar") == "lead":
                    v.pop("lugar")
            nota["lugar"] = "lead"
        elif lugar == "lado":
            lados = sorted([v for v in datos["notas"] if v.get("lugar") == "lado"], key=lambda v: v.get("fecha", ""))
            while len(lados) >= 2:
                viejo = lados.pop(0)
                viejo.pop("lugar", None)
                viejo.pop("sinFotoEnPortada", None)
            nota["lugar"] = "lado"
        datos["notas"].append(nota)
        ids.add(nid)
        agregadas.append(nota)
        if n.get("origen"):
            vistas.add(n["origen"].split("?")[0])

    vistas.update(u.split("?")[0] for u in entrada.get("descartadas", []))

    # Recorte: se borran las notas más viejas sin lugar fijo en la portada (y sus fotos)
    datos["notas"].sort(key=lambda v: v.get("fecha", ""), reverse=True)
    borradas = []
    while len(datos["notas"]) > MAX_NOTAS:
        idx = next((j for j in range(len(datos["notas"]) - 1, -1, -1) if not datos["notas"][j].get("lugar")), None)
        if idx is None:
            break
        vieja = datos["notas"].pop(idx)
        borradas.append(vieja["id"])
        ruta = os.path.join(FOTOS, vieja["id"] + ".jpg")
        if os.path.exists(ruta):
            os.remove(ruta)

    json.dump(datos, open(DATOS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sorted(vistas), open(VISTAS, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(uso, open(USO, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    os.replace(ENTRADA, os.path.join(AUTO, "ultima_entrada.json"))
    linea = f"{ahora:%Y-%m-%d %H:%M} agregadas={len(agregadas)} descartadas={len(entrada.get('descartadas', []))} borradas={len(borradas)} | " + \
            "; ".join(a["titulo"][:70] for a in agregadas)
    with open(REGISTRO, "a", encoding="utf-8") as f:
        f.write(linea + "\n")
    traba = os.path.join(AUTO, ".actualizando")
    if os.path.exists(traba):
        os.remove(traba)
    print(linea)

if __name__ == "__main__":
    main()
