import asyncio
import base64
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from playwright.async_api import async_playwright
import resend

URL = "https://www.santafe.gob.ar/seturnosweb/"
TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")

DATOS = {
    "nombre": "Paola Fabiana",
    "apellido": "Veron",
    "documento": "24470091",
    "unidad": "Unidad 16, PEREZ",
    "menores": "0"
}

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_DESTINATARIO = os.getenv("EMAIL_DESTINATARIO")
MODO_TEST = os.getenv("MODO_TEST", "false").lower() == "true"
MAX_REINTENTOS = 3
MAX_ESPERA_TURNOS = 300  # Máximo 5 minutos esperando que se actualicen los turnos
INTERVALO_RECARGA = 5    # Segundos entre recargas de página

def calcular_proximo_miercoles():
    ahora = datetime.now(TIMEZONE)
    dias_hasta_miercoles = (2 - ahora.weekday()) % 7
    if dias_hasta_miercoles == 0:
        dias_hasta_miercoles = 7
    proximo_miercoles = ahora + timedelta(days=dias_hasta_miercoles)
    return proximo_miercoles

def obtener_hora_objetivo():
    """
    Obtiene la hora objetivo para ejecutar.
    Si se pasa HORA_OBJETIVO env var (formato HH:MM o HH:MM:SS), usa esa hora del día actual.
    Si no, usa medianoche (00:00:01) del día siguiente si es después de mediodía,
    o del día actual si es antes de mediodía.
    """
    ahora = datetime.now(TIMEZONE)
    hora_objetivo_env = os.getenv("HORA_OBJETIVO")

    if hora_objetivo_env:
        try:
            partes = hora_objetivo_env.split(":")
            hora = int(partes[0])
            minuto = int(partes[1])
            segundo = int(partes[2]) if len(partes) >= 3 else 0
            objetivo = datetime(ahora.year, ahora.month, ahora.day, hora, minuto, segundo, tzinfo=TIMEZONE)
            # Si la hora ya pasó hoy, usar mañana
            if objetivo <= ahora:
                objetivo += timedelta(days=1)
            return objetivo
        except ValueError:
            print(f"HORA_OBJETIVO inválida: {hora_objetivo_env}, usando medianoche")

    # Default: medianoche
    if ahora.hour >= 12:
        manana = ahora + timedelta(days=1)
        return datetime(manana.year, manana.month, manana.day, 0, 0, 1, tzinfo=TIMEZONE)
    else:
        return datetime(ahora.year, ahora.month, ahora.day, 0, 0, 1, tzinfo=TIMEZONE)

def esperar_hasta_hora_objetivo():
    """
    Espera hasta la hora objetivo con precisión de milisegundos.
    Diseñado para ser disparado ~10-30 segundos antes por cron-job.org.
    """
    import time

    objetivo = obtener_hora_objetivo()
    ahora = datetime.now(TIMEZONE)

    segundos_restantes = (objetivo - ahora).total_seconds()

    if segundos_restantes <= 0:
        print("Ya pasó la hora objetivo, ejecutando inmediatamente...")
        return

    # Máximo 5 minutos de espera - si es más, algo está mal configurado
    if segundos_restantes > 300:
        raise Exception(f"Demasiado tiempo de espera ({segundos_restantes:.0f} seg). El trigger debe dispararse ~30 seg antes de la hora objetivo.")

    print(f"Hora actual (Argentina): {ahora.strftime('%Y-%m-%d %H:%M:%S.%f')}")
    print(f"Hora objetivo: {objetivo.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Esperando {segundos_restantes:.1f} segundos...")

    # Espera gruesa hasta 2 segundos antes
    while True:
        ahora = datetime.now(TIMEZONE)
        segundos_restantes = (objetivo - ahora).total_seconds()

        if segundos_restantes <= 2:
            break
        elif segundos_restantes > 10:
            print(f"  Faltan {segundos_restantes:.0f} segundos...")
            time.sleep(5)
        else:
            time.sleep(0.5)

    # Espera fina con alta precisión
    while True:
        ahora = datetime.now(TIMEZONE)
        if ahora >= objetivo:
            print(f"¡HORA EXACTA! {ahora.strftime('%H:%M:%S.%f')}")
            break
        time.sleep(0.01)  # 10ms de precisión

def enviar_email(pdf_path: str, fecha_visita: str):
    if not RESEND_API_KEY or not EMAIL_DESTINATARIO:
        print("RESEND_API_KEY o EMAIL_DESTINATARIO no configurados, saltando envio de email")
        return False
    
    resend.api_key = RESEND_API_KEY
    
    with open(pdf_path, "rb") as f:
        pdf_content = f.read()
    
    pdf_base64 = base64.b64encode(pdf_content).decode("utf-8")
    
    destinatarios = [email.strip() for email in EMAIL_DESTINATARIO.split(",")]
    print(f"Destinatarios: {destinatarios}")
    
    exitos = 0
    for destinatario in destinatarios:
        print(f"Enviando email a: {destinatario}...")
        
        params = {
            "from": "Turno Penitenciario <turno@ramiroschenone-dev.com>",
            "to": [destinatario],
            "subject": f"Turno Penitenciario - {fecha_visita}",
            "html": f"""
            <h2>Turno Generado Exitosamente</h2>
            <p>Se ha generado el turno para la visita del <strong>{fecha_visita}</strong>.</p>
            <p><strong>Datos:</strong></p>
            <ul>
                <li>Nombre: {DATOS['nombre']} {DATOS['apellido']}</li>
                <li>DNI: {DATOS['documento']}</li>
                <li>Unidad: {DATOS['unidad']}</li>
                <li>Fecha de visita: {fecha_visita}</li>
            </ul>
            <p>El comprobante PDF se adjunta a este correo.</p>
            """,
            "attachments": [
                {
                    "filename": f"turno_{fecha_visita.replace('/', '-')}.pdf",
                    "content": pdf_base64
                }
            ]
        }
        
        try:
            response = resend.Emails.send(params)
            print(f"  -> Enviado a {destinatario}: {response}")
            exitos += 1
        except Exception as e:
            print(f"  -> Error enviando a {destinatario}: {e}")
    
    print(f"Emails enviados: {exitos}/{len(destinatarios)}")
    return exitos > 0

async def preparar_formulario(page, fecha_visita):
    print("Navegando a la pagina...")
    await page.goto(URL, wait_until="networkidle")
    await page.wait_for_timeout(2000)
    
    print("Seleccionando Unidad 16, PEREZ...")
    unidad_select = page.locator("select").first
    await unidad_select.select_option(value="Unidad 16, PEREZ")
    
    print(f"Llenando nombre: {DATOS['nombre']}")
    nombre_input = page.get_by_placeholder("Nombre*")
    await nombre_input.fill(DATOS["nombre"])
    
    print(f"Llenando apellido: {DATOS['apellido']}")
    apellido_input = page.get_by_placeholder("Apellido*")
    await apellido_input.fill(DATOS["apellido"])
    
    fecha_str = fecha_visita.strftime('%d/%m/%Y')
    print(f"Seleccionando fecha: {fecha_str}")
    date_input = page.locator("input[type='date']")
    fecha_formato_input = fecha_visita.strftime("%Y-%m-%d")
    await date_input.fill(fecha_formato_input)
    
    print(f"Llenando documento: {DATOS['documento']}")
    documento_input = page.get_by_placeholder("DOCUMENTO*")
    await documento_input.fill(DATOS["documento"])
    
    print(f"Seleccionando menores: {DATOS['menores']}")
    menores_select = page.locator("select").nth(1)
    await menores_select.select_option(value=DATOS["menores"])
    
    print("Formulario preparado, listo para enviar...")
    return fecha_str

async def esperar_turnos_disponibles(page, fecha_visita):
    """
    Refresca la página hasta que el atributo 'max' del campo fecha
    permita nuestra fecha objetivo. Solo carga la página y selecciona
    la unidad (para obtener el max correcto), sin llenar el resto.
    """
    import time
    inicio = time.time()
    intento = 0
    fecha_objetivo = fecha_visita.strftime("%Y-%m-%d")

    while True:
        intento += 1
        print(f"Verificando disponibilidad de turnos (intento #{intento})...")
        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # Seleccionar unidad primero (puede afectar las fechas disponibles)
        unidad_select = page.locator("select").first
        await unidad_select.select_option(value=DATOS["unidad"])
        await page.wait_for_timeout(500)

        date_input = page.locator("input[type='date']")
        max_attr = await date_input.get_attribute("max")

        print(f"  max fecha={max_attr}, objetivo={fecha_objetivo}")

        if max_attr is None or max_attr >= fecha_objetivo:
            print(f"Turnos disponibles! Fecha {fecha_objetivo} permitida (max={max_attr})")
            return True

        transcurrido = time.time() - inicio
        if transcurrido >= MAX_ESPERA_TURNOS:
            print(f"Timeout: turnos no disponibles despues de {MAX_ESPERA_TURNOS}s")
            print(f"  max={max_attr}, necesitamos>={fecha_objetivo}")
            return False

        restante = MAX_ESPERA_TURNOS - transcurrido
        print(f"  Turnos no disponibles aun. Reintentando en {INTERVALO_RECARGA}s (quedan {restante:.0f}s)...")
        await page.wait_for_timeout(INTERVALO_RECARGA * 1000)


async def enviar_formulario_con_reintentos(page, downloads_path, fecha_visita):
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            generar_btn = page.get_by_role("button", name="Generar Turno")
            print(f"Intento {intento}/{MAX_REINTENTOS} - Haciendo clic en GENERAR TURNO...")
            hora_click = datetime.now(TIMEZONE)
            print(f"Hora del click: {hora_click.strftime('%H:%M:%S.%f')}")

            async with page.expect_download(timeout=15000) as download_info:
                await generar_btn.click()

            download = await download_info.value
            pdf_path = downloads_path / f"turno_{datetime.now(TIMEZONE).strftime('%Y%m%d_%H%M%S')}.pdf"
            await download.save_as(pdf_path)
            print(f"PDF guardado en: {pdf_path}")
            return pdf_path

        except Exception as e:
            print(f"Intento {intento} fallido: {e}")
            screenshot_path = downloads_path / f"error_intento{intento}_{datetime.now(TIMEZONE).strftime('%Y%m%d_%H%M%S')}.png"
            await page.screenshot(path=str(screenshot_path))
            print(f"Screenshot guardado: {screenshot_path}")

            if intento < MAX_REINTENTOS:
                print("Recargando pagina y re-llenando formulario...")
                await preparar_formulario(page, fecha_visita)
            else:
                print("Todos los intentos fallaron")
                return None

    return None

async def run():
    downloads_path = Path(__file__).parent / "downloads"
    downloads_path.mkdir(exist_ok=True)

    fecha_visita = calcular_proximo_miercoles()
    print(f"Fecha de visita calculada: {fecha_visita.strftime('%d/%m/%Y')}")

    if MODO_TEST:
        print("\n" + "="*50)
        print("MODO TEST - ENVIANDO INMEDIATAMENTE")
        print("="*50 + "\n")
    else:
        print("\n" + "="*50)
        print("MODO PRODUCCION - ESPERANDO HORA OBJETIVO")
        print("="*50 + "\n")

        # Esperar ANTES de abrir el navegador para evitar timeout de sesión
        esperar_hasta_hora_objetivo()

        print("\n" + "="*50)
        print("¡CARGANDO FORMULARIO Y ENVIANDO!")
        print("="*50 + "\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        # 1. Esperar a que los turnos estén disponibles (refrescando hasta que max >= fecha)
        turnos_listos = await esperar_turnos_disponibles(page, fecha_visita)
        if not turnos_listos:
            print("No se pudieron actualizar los turnos. Abortando.")
            await browser.close()
            return None

        # 2. Ahora que sabemos que la fecha es válida, llenar el formulario completo
        fecha_str = await preparar_formulario(page, fecha_visita)

        # 3. Enviar
        pdf_path = await enviar_formulario_con_reintentos(page, downloads_path, fecha_visita)

        await browser.close()
    
    if pdf_path and pdf_path.exists():
        print("Enviando email con el PDF...")
        enviar_email(str(pdf_path), fecha_str)
        
    return str(pdf_path) if pdf_path else None

async def main():
    try:
        result = await run()
        if result:
            print(f"Proceso completado exitosamente. PDF: {result}")
        else:
            print("Proceso completado sin PDF")
    except Exception as e:
        print(f"Error durante la ejecucion: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
