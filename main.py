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

def calcular_proximo_miercoles():
    ahora = datetime.now(TIMEZONE)
    dias_hasta_miercoles = (2 - ahora.weekday()) % 7
    if dias_hasta_miercoles == 0:
        dias_hasta_miercoles = 7
    proximo_miercoles = ahora + timedelta(days=dias_hasta_miercoles)
    return proximo_miercoles

def obtener_siguiente_medianoche():
    ahora = datetime.now(TIMEZONE)
    manana = ahora.replace(hour=0, minute=0, second=1, microsecond=0) + timedelta(days=1)
    return manana

def esperar_hasta_medianoche():
    objetivo = obtener_siguiente_medianoche()
    ahora = datetime.now(TIMEZONE)
    
    if ahora >= objetivo:
        print("Ya pasó la medianoche, ejecutando inmediatamente...")
        return
    
    segundos_restantes = (objetivo - ahora).total_seconds()
    print(f"Hora actual (Argentina): {ahora.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Objetivo: {objetivo.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Esperando {segundos_restantes:.2f} segundos hasta las 00:00:01...")
    
    while True:
        ahora = datetime.now(TIMEZONE)
        segundos_restantes = (objetivo - ahora).total_seconds()
        
        if segundos_restantes <= 0:
            print(f"¡Es la hora! {ahora.strftime('%H:%M:%S.%f')}")
            break
        
        if segundos_restantes > 60:
            print(f"  Faltan {segundos_restantes:.0f} segundos...")
            import time
            time.sleep(30)
        elif segundos_restantes > 5:
            import time
            time.sleep(1)
        else:
            import time
            time.sleep(0.1)

def enviar_email(pdf_path: str, fecha_visita: str):
    if not RESEND_API_KEY or not EMAIL_DESTINATARIO:
        print("RESEND_API_KEY o EMAIL_DESTINATARIO no configurados, saltando envio de email")
        return False
    
    resend.api_key = RESEND_API_KEY
    
    with open(pdf_path, "rb") as f:
        pdf_content = f.read()
    
    pdf_base64 = base64.b64encode(pdf_content).decode("utf-8")
    
    destinatarios = [email.strip() for email in EMAIL_DESTINATARIO.split(",")]
    print(f"Enviando a: {destinatarios}")
    
    params = {
        "from": "Turno Penitenciario <onboarding@resend.dev>",
        "to": destinatarios,
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
        print(f"Email enviado exitosamente: {response}")
        return True
    except Exception as e:
        print(f"Error enviando email: {e}")
        return False

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

async def enviar_formulario_con_reintentos(page, downloads_path):
    generar_btn = page.get_by_role("button", name="Generar Turno")
    
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
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
            if intento < MAX_REINTENTOS:
                print("Reintentando en 1 segundo...")
                await page.wait_for_timeout(1000)
            else:
                print("Todos los intentos fallaron")
                screenshot_path = downloads_path / f"error_{datetime.now(TIMEZONE).strftime('%Y%m%d_%H%M%S')}.png"
                await page.screenshot(path=str(screenshot_path))
                print(f"Screenshot de error guardado en: {screenshot_path}")
                return None
    
    return None

async def run():
    downloads_path = Path(__file__).parent / "downloads"
    downloads_path.mkdir(exist_ok=True)
    
    fecha_visita = calcular_proximo_miercoles()
    print(f"Fecha de visita calculada: {fecha_visita.strftime('%d/%m/%Y')}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
        fecha_str = await preparar_formulario(page, fecha_visita)
        
        if MODO_TEST:
            print("\n" + "="*50)
            print("MODO TEST - ENVIANDO INMEDIATAMENTE")
            print("="*50 + "\n")
        else:
            print("\n" + "="*50)
            print("MODO PRODUCCION - ESPERANDO HORA EXACTA (00:00:01)")
            print("="*50 + "\n")
            
            esperar_hasta_medianoche()
            
            print("\n" + "="*50)
            print("¡ENVIANDO FORMULARIO!")
            print("="*50 + "\n")
        
        pdf_path = await enviar_formulario_con_reintentos(page, downloads_path)
        
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
