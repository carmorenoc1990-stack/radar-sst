# Radar Normativo SST · Perú

Uso personal. Cada día revisa gob.pe, filtra normas de seguridad y salud en el trabajo, las guarda en `data/normas.json` y te avisa por Telegram. La página `index.html` es el buscador.

## Archivos

- `index.html`: buscador con filtros (tipo, entidad, tema, estado), marca "NUEVA" y notas propias en cada norma.
- `scripts/fetch_normas.py`: lee las fuentes, filtra por palabras clave y avisa.
- `.github/workflows/normas.yml`: lo ejecuta todos los días a las 7:30 am (hora de Perú).
- `data/normas.json`: la base. Trae 6 normas de ejemplo (`"demo": true`) que se borran solas en la primera corrida real.

## Puesta en marcha (unos 15 minutos)

1. **Crea el repositorio.** En GitHub, crea un repo (puede ser privado) y sube toda esta carpeta, incluida `.github`.
2. **Crea el bot de Telegram.**
   - En Telegram habla con `@BotFather`, escribe `/newbot` y copia el token.
   - Envíale cualquier mensaje a tu bot nuevo.
   - Abre `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y copia el número que aparece en `"chat":{"id": ...}`.
3. **Guarda los secretos.** En el repo: Settings → Secrets and variables → Actions → New repository secret. Crea `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
4. **Primera corrida.** Pestaña Actions → "Revisar normas SST" → Run workflow. Revisa el registro: debe decir cuántas normas encontró en cada listado.
5. **Publica la página.** Settings → Pages → Branch `main`, carpeta `/ (root)`. Si el repo es privado, GitHub Pages exige un plan de pago; en ese caso abre la página en tu computadora con `python -m http.server` dentro de la carpeta, o haz el repo público (solo contiene normas, que son públicas).

## Probar en tu computadora

```
python scripts/fetch_normas.py
python -m http.server
```

Luego abre http://localhost:8000.

## Ajustes

- **Más o menos fuentes:** edita `FUENTES` en el script (por ejemplo MINEM, MVCS, OSINERGMIN con su listado de normas en gob.pe).
- **Qué se considera SST:** edita `PALABRAS_CLAVE`. Si una norma importante no te llega, agrega aquí un término que use.
- **Temas:** edita el diccionario `TEMAS`.

## Límites que debes conocer

- El script lee el HTML de los listados de gob.pe. Si gob.pe cambia su diseño, el registro de la corrida mostrará 0 normas por fuente y Telegram te avisará si fallan todas. Entonces hay que ajustar `parsear_listado`.
- El filtro es por palabras clave sobre el título y el texto del listado, no sobre el contenido completo de la norma. Revisa los primeros meses.
- El campo `estado` de las normas nuevas es "vigente" salvo que el título diga "deroga". La vigencia real (modificada, derogada) se confirma en SPIJ o en El Peruano; puedes corregirla a mano en `data/normas.json`.
- Las normas de ejemplo son solo para ver cómo funciona la página.
