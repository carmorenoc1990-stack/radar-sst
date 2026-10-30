#!/usr/bin/env python3
"""Radar Normativo SST Perú.

Lee los listados de normas legales de gob.pe (MTPE, SUNAFIL, MINSA, etc.),
filtra por palabras clave de SST, agrega las nuevas a data/normas.json y
avisa por Telegram. Solo usa la librería estándar de Python.

Variables de entorno (opcionales):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  -> para recibir el aviso
"""
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVO = os.path.join(RAIZ, "data", "normas.json")

# Fuentes: listados HTML de normas legales en gob.pe.
# Verifica que cada URL abra en tu navegador; puedes agregar o quitar entidades.
FUENTES = [
    {"entidad": "MTPE", "url": "https://www.gob.pe/institucion/mtpe/normas-legales"},
    {"entidad": "SUNAFIL", "url": "https://www.gob.pe/institucion/sunafil/normas-legales"},
    {"entidad": "MINSA", "url": "https://www.gob.pe/institucion/minsa/normas-legales"},
    {"entidad": "Presidencia", "url": "https://www.gob.pe/institucion/presidencia/normas-legales"},
]
PAGINAS_POR_FUENTE = 2  # cuántas páginas del listado revisar (más páginas = más historia)

# Diario Oficial El Peruano: se lee su sitemap oficial de normas legales (su robots.txt lo permite).
ELPERUANO_SITEMAP = "https://busquedas.elperuano.pe/sitemap/sitemap-normas_legales.xml"
ELPERUANO_BASE = "https://busquedas.elperuano.pe/dispositivo/NL/"
ELPERUANO_MAX_POR_CORRIDA = 150   # páginas nuevas que se abren por ejecución
ELPERUANO_PAUSA = 0.4             # segundos entre páginas, para no sobrecargar el sitio
ELPERUANO_ACTIVO = True           # ponlo en False para desactivar esta fuente

# FUERTES: si aparecen, la norma es de SST casi seguro.
PALABRAS_FUERTES = [
    "seguridad y salud en el trabajo", "seguridad y salud ocupacional", "29783",
    "accidente de trabajo", "accidentes de trabajo", "enfermedad ocupacional",
    "enfermedades ocupacionales", "riesgos psicosociales", "ergonomi",
    "examen medico ocupacional", "examenes medicos ocupacionales",
    "equipo de proteccion personal", "comite de seguridad", "supervisor de seguridad",
    "trabajo en altura", "espacios confinados", "seguridad minera",
    "seguridad y salud minera", "seguridad en construccion", "g.050",
    "peligros y riesgos", "salud ocupacional", "pensiones y riesgos del trabajo",
    "sctr", "riesgos laborales", "riesgo laboral", "silice", "ruido ocupacional",
]
# MEDIAS: relacionadas, pero solo entran si no parecen un trámite administrativo.
PALABRAS_MEDIAS = [
    "inspeccion del trabajo", "inspeccion laboral", "fiscalizacion laboral",
    "hostigamiento", "teletrabajo", "trabajo remoto", "escala de multas",
    "protocolo de fiscalizacion", "protocolo de inspeccion", "sano y seguro",
    "seguridad laboral", "salud laboral", "prevencion de riesgos",
]
# Trámites internos que no son normas de SST (se descartan siempre).
ADMIN_DURO = [
    "designar", "designacion", "encargar", "encargatura", "dar por concluid",
    "autorizar el viaje", "comision de servicios", "aceptar la renuncia",
    "declarar improcedente", "declarar infundad", "declarar fundad", "declarar nul",
    "prescripcion de la exigibilidad", "recurso de apelacion", "recurso de reconsideracion",
    "auxiliar coactivo", "cargo de confianza", "vacaciones", "licencia",
]
# Trámites que además descartan las coincidencias "medias".
ADMIN_BLANDO = [
    "multa", "contrato", "personal", "concurso", "cas ", "servidor", "viaje",
    "ejecucion coactiva", "procedimiento sancionador", "direccion regional",
]

TEMAS = {
    "SGSST": ["sistema de gestion", "29783", "reglamento interno", "iperc", "matriz"],
    "comités": ["comite de seguridad", "supervisor de seguridad"],
    "exámenes médicos": ["examen medico", "examenes medicos", "vigilancia de la salud"],
    "accidentes": ["accidente", "incidente peligroso", "notificacion"],
    "riesgos psicosociales": ["psicosocial", "hostigamiento", "estres"],
    "ergonomía": ["ergonomi", "disergonomico"],
    "construcción": ["construccion", "g.050", "altura"],
    "minería": ["mineria", "minera", "minero"],
    "inspección": ["sunafil", "inspeccion", "sancion", "multa", "infraccion"],
    "EPP": ["equipo de proteccion", "epp"],
    "salud": ["salud ocupacional", "enfermedad ocupacional", "sctr", "pensiones"],
    "teletrabajo": ["teletrabajo", "trabajo remoto"],
}

TIPOS = [
    ("Decreto Supremo", r"decreto supremo"),
    ("Decreto Legislativo", r"decreto legislativo"),
    ("Decreto de Urgencia", r"decreto de urgencia"),
    ("Ley", r"\bley\b"),
    ("Resolución Ministerial", r"resoluci[oó]n ministerial"),
    ("Resolución de Superintendencia", r"resoluci[oó]n de superintendencia"),
    ("Resolución Suprema", r"resoluci[oó]n suprema"),
    ("Resolución Directoral", r"resoluci[oó]n directoral"),
    ("Resolución de Intendencia", r"resoluci[oó]n de intendencia"),
    ("Resolución Viceministerial", r"resoluci[oó]n viceministerial"),
    ("Resolución", r"resoluci[oó]n"),
    ("Reglamento", r"reglamento"),
    ("Norma Técnica", r"norma t[eé]cnica"),
]
MESES = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
     "agosto", "setiembre", "octubre", "noviembre", "diciembre"])}
MESES["septiembre"] = 9


def sin_tildes(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def descargar(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RadarNormativoSST/1.0; uso personal)",
        "Accept-Language": "es-PE,es;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def texto_limpio(fragmento):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", fragmento, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"<[^>]*$", " ", t)  # etiqueta cortada al final del fragmento
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def buscar_fecha(texto):
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:de|del)\s+(\d{4})", texto, re.I)
    if m:
        mes = MESES.get(sin_tildes(m.group(2)))
        if mes:
            try:
                return date(int(m.group(3)), mes, int(m.group(1))).isoformat()
            except ValueError:
                pass
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    return ""


def parsear_listado(pagina_html, entidad, base_url):
    """Devuelve normas encontradas en un listado de gob.pe.

    Busca enlaces tipo /institucion/<ent>/normas-legales/<id>-<slug>.
    """
    resultado = []
    patron = re.compile(
        r'<a[^>]+href="([^"]*?/normas-legales/(\d+)-[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
    vistos = set()
    coincidencias = list(patron.finditer(pagina_html))
    for i, m in enumerate(coincidencias):
        href, nid, interior = m.group(1), m.group(2), m.group(3)
        if nid in vistos:
            continue
        titulo = texto_limpio(interior)
        if len(titulo) < 8:
            continue
        vistos.add(nid)
        # El contexto llega solo hasta el siguiente enlace de norma, para no mezclar entradas.
        fin = coincidencias[i + 1].start() if i + 1 < len(coincidencias) else m.end() + 900
        contexto = texto_limpio(pagina_html[m.end(): min(fin, m.end() + 900)])
        resultado.append({
            "id": "gobpe-" + nid,
            "titulo": titulo,
            "entidad": entidad,
            "url": urllib.parse.urljoin(base_url, href),
            "fecha": buscar_fecha(titulo) or buscar_fecha(contexto[:400]),
            "resumen": contexto[:280].rsplit(" ", 1)[0] if contexto else "",
        })
    return resultado


def clasificar_tipo(titulo):
    for nombre, patron in TIPOS:
        if re.search(patron, titulo, re.I):
            return nombre
    return "Otra norma"


def es_sst(n):
    base = sin_tildes(n["titulo"] + " " + n.get("resumen", ""))
    if any(k in base for k in ADMIN_DURO):
        return False
    if any(k in base for k in PALABRAS_FUERTES):
        return True
    if any(k in base for k in PALABRAS_MEDIAS):
        return not any(k in base for k in ADMIN_BLANDO)
    return False


def detectar_temas(n):
    base = sin_tildes(n["titulo"] + " " + n.get("resumen", ""))
    temas = [t for t, claves in TEMAS.items() if any(sin_tildes(c) in base for c in claves)]
    return temas or ["general"]


def estado_inicial(titulo):
    t = sin_tildes(titulo)
    if "deroga" in t:
        return "derogada"  # la norma nueva deroga a otra; revisa a mano
    return "vigente"


def clave_norma(n):
    """Clave tipo+número (ej. 'Resolución Ministerial|326-2026-TR') para no duplicar una misma
    norma que llega por gob.pe y por El Peruano."""
    t = sin_tildes(n.get("titulo", "")).upper()
    m = re.search(r"(\d{1,6})-(\d{4})((?:[-/][A-Z0-9]+)*)", t)
    if not m:
        return ""
    numero = f"{m.group(1)}-{m.group(2)}{m.group(3)}".replace("/", "-")
    return f"{clasificar_tipo(n.get('titulo', ''))}|{numero}"


def meta(pagina, nombre):
    """Lee el contenido de una etiqueta <meta property|name="nombre" content="...">."""
    for patron in (
        r'<meta[^>]+(?:property|name)=["\']' + re.escape(nombre) + r'["\'][^>]*content=["\']([^"\']*)["\']',
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']' + re.escape(nombre) + r'["\']',
    ):
        m = re.search(patron, pagina, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def normalizar_entidad(texto):
    t = sin_tildes(texto)
    reglas = [
        ("trabajo y promocion del empleo", "MTPE"), ("fiscalizacion laboral", "SUNAFIL"),
        ("ministerio de salud", "MINSA"), ("energia y minas", "MINEM"),
        ("vivienda, construccion", "MVCS"), ("inversion en energia y mineria", "OSINERGMIN"),
        ("consejo de ministros", "PCM"), ("congreso de la republica", "Congreso"),
        ("presidencia de la republica", "Presidencia"),
    ]
    for clave, sigla in reglas:
        if clave in t:
            return sigla
    return texto.strip().title()[:60] or "El Peruano"


def parsear_elperuano(pagina, nid):
    """Extrae una norma de una página busquedas.elperuano.pe/dispositivo/NL/<id>."""
    cabeza = pagina[:120000]
    titulo_meta = meta(cabeza, "og:title")
    if not titulo_meta:
        m = re.search(r"<title[^>]*>(.*?)</title>", cabeza, re.S | re.I)
        titulo_meta = texto_limpio(m.group(1)) if m else ""
    if not titulo_meta:
        return None
    # El título termina con un sufijo tipo " - RESOLUCIÓN -" o " - Ordenanzas -"
    suf = re.search(r"\s*-\s*([A-Za-zÁÉÍÓÚÑáéíóúñ ]{3,40})\s*-\s*$", titulo_meta)
    sumilla = titulo_meta[:suf.start()].strip() if suf else titulo_meta
    tipo_sufijo = suf.group(1).strip() if suf else ""

    h2 = [texto_limpio(x) for x in re.findall(r"<h2[^>]*>(.*?)</h2>", cabeza, re.S | re.I)]
    h2 = [x for x in h2 if re.search(r"[A-Za-zÁÉÍÓÚáéíóú]", x)]
    numero = next((x for x in h2 if re.search(r"N[º°o]\.?\s*\d", x, re.I)), "")
    entidad_h2 = h2[0] if h2 and h2[0] != numero else ""
    tipo_h2 = ""
    for x in h2:
        if x != numero and x != entidad_h2 and any(re.search(pt, x, re.I) for _, pt in TIPOS):
            tipo_h2 = x
            break
    tipo_txt = tipo_h2 or tipo_sufijo
    tipo = clasificar_tipo(tipo_txt) if tipo_txt else clasificar_tipo(sumilla)
    if tipo == "Otra norma" and tipo_sufijo:
        tipo = tipo_sufijo.title()

    nombre = " ".join(x for x in [tipo_h2.title() if tipo_h2 else tipo, numero.replace("Nº", "N.°")] if x)
    fecha = ""
    m = re.search(r"Fecha de publicaci[oó]n:?\s*(?:<[^>]*>\s*)*(\d{1,2})/(\d{1,2})/(\d{4})", cabeza, re.I)
    if m:
        try:
            fecha = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    return {
        "id": "elperuano-" + nid,
        "titulo": nombre or sumilla[:120],
        "tipo": tipo,
        "entidad": normalizar_entidad(entidad_h2) if entidad_h2 else "El Peruano",
        "fecha": fecha,
        "url": ELPERUANO_BASE + nid,
        "resumen": sumilla[:400],
    }


def leer_elperuano(db, existentes, claves, nuevas, errores):
    """Lee el sitemap de El Peruano y agrega a `nuevas` las normas SST que aún no teníamos."""
    vistos = set(db.get("vistos_elperuano", []))
    try:
        xml = descargar(ELPERUANO_SITEMAP)
    except Exception as e:  # noqa: BLE001
        errores.append(f"El Peruano sitemap: {e}")
        return
    ids = re.findall(r"/dispositivo/NL/(\d+-\d+)\s*</loc>", xml)
    pendientes = sorted((i for i in dict.fromkeys(ids) if i not in vistos),
                        key=lambda s: int(s.split("-")[0]), reverse=True)
    print(f"El Peruano: {len(ids)} normas en el sitemap, {len(pendientes)} sin revisar")
    revisadas = fallos = seguidos = 0
    for nid in pendientes[:ELPERUANO_MAX_POR_CORRIDA]:
        time.sleep(ELPERUANO_PAUSA)
        try:
            pagina = descargar(ELPERUANO_BASE + nid)
        except Exception as e:  # noqa: BLE001
            fallos += 1
            seguidos += 1
            if seguidos >= 5:
                errores.append(f"El Peruano: 5 fallos seguidos, se detiene ({e})")
                break
            continue
        seguidos = 0
        vistos.add(nid)
        revisadas += 1
        n = parsear_elperuano(pagina, nid)
        if not n or n["id"] in existentes or not es_sst(n):
            continue
        k = clave_norma(n)
        if k and k in claves:
            continue  # ya la teníamos por gob.pe
        existentes.add(n["id"])
        if k:
            claves.add(k)
        n.update({
            "temas": detectar_temas(n),
            "estado": estado_inicial(n["titulo"] + " " + n["resumen"]),
            "detectada": date.today().isoformat(),
        })
        nuevas.append(n)
    db["vistos_elperuano"] = sorted(vistos, key=lambda s: int(s.split("-")[0]), reverse=True)[:6000]
    print(f"El Peruano: {revisadas} páginas revisadas, {fallos} con error")


def telegram(texto):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram] sin token/chat configurado; se omite el aviso")
        return
    datos = urllib.parse.urlencode({
        "chat_id": chat, "text": texto[:4000],
        "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=datos),
            timeout=30).read()
    except urllib.error.URLError as e:
        print("[telegram] error:", e)


def cargar():
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, encoding="utf-8") as f:
            return json.load(f)
    return {"actualizado": "", "normas": []}


def guardar(db):
    os.makedirs(os.path.dirname(ARCHIVO), exist_ok=True)
    db["actualizado"] = datetime.now().isoformat(timespec="seconds")
    db["normas"].sort(key=lambda n: (n.get("fecha") or "", n.get("detectada") or ""), reverse=True)
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def main():
    db = cargar()
    # Limpieza: vuelve a aplicar el filtro a lo ya guardado y quita lo que no es SST.
    antes = len(db["normas"])
    db["normas"] = [n for n in db["normas"] if n.get("demo") or es_sst(n)]
    if len(db["normas"]) != antes:
        print(f"Limpieza: se quitaron {antes - len(db['normas'])} normas que no son de SST")
    hubo_demo = any(n.get("demo") for n in db["normas"])
    existentes = {n["id"] for n in db["normas"] if not n.get("demo")}
    claves = {clave_norma(n) for n in db["normas"] if clave_norma(n)}
    nuevas, errores = [], []

    for fuente in FUENTES:
        for pag in range(1, PAGINAS_POR_FUENTE + 1):
            url = fuente["url"] + (f"?sheet={pag}" if pag > 1 else "")
            try:
                contenido = descargar(url)
            except Exception as e:  # noqa: BLE001
                errores.append(f"{fuente['entidad']} p{pag}: {e}")
                break
            hallazgos = parsear_listado(contenido, fuente["entidad"], url)
            print(f"{fuente['entidad']} p{pag}: {len(hallazgos)} normas en el listado")
            for n in hallazgos:
                if n["id"] in existentes or not es_sst(n):
                    continue
                k = clave_norma({"titulo": n["titulo"]})
                if k and k in claves:
                    continue  # la misma norma ya llegó por otra fuente
                existentes.add(n["id"])
                if k:
                    claves.add(k)
                n.update({
                    "tipo": clasificar_tipo(n["titulo"]),
                    "temas": detectar_temas(n),
                    "estado": estado_inicial(n["titulo"]),
                    "detectada": date.today().isoformat(),
                })
                nuevas.append(n)

    if ELPERUANO_ACTIVO:
        leer_elperuano(db, existentes, claves, nuevas, errores)

    if nuevas and hubo_demo:
        db["normas"] = [n for n in db["normas"] if not n.get("demo")]
        primera_vez = True
    else:
        primera_vez = False
    db["normas"].extend(nuevas)
    guardar(db)
    print(f"Nuevas normas SST: {len(nuevas)}")

    # En ejecución manual (botón Run workflow) avisa siempre, para confirmar que Telegram funciona.
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and not nuevas:
        telegram(f"✅ Radar SST funciona. Revisión manual: 0 normas nuevas, "
                 f"{len(db['normas'])} en la lista.")

    if errores:
        print("Errores:", *errores, sep="\n  ")
        if len(errores) == len(FUENTES):
            telegram("⚠️ Radar SST: no pude leer ninguna fuente hoy. Revisa el workflow en GitHub Actions.")
            return 1

    if nuevas:
        if primera_vez and len(nuevas) > 8:
            telegram(f"✅ Radar SST listo: cargué {len(nuevas)} normas iniciales. "
                     "De aquí en adelante solo te aviso las nuevas.")
        else:
            lineas = [f"📢 <b>{len(nuevas)} norma(s) SST nueva(s)</b>"]
            for n in nuevas[:15]:
                lineas.append(f"\n• <b>{html.escape(n['tipo'])}</b> · {html.escape(n['entidad'])}"
                              f"\n{html.escape(n['titulo'][:120])}"
                              f"\n{html.escape((n.get('resumen') or '')[:180])}\n{n['url']}")
            telegram("\n".join(lineas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
