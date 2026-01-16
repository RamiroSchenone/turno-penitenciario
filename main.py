import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

URL = "https://www.santafe.gob.ar/seturnosweb/"

DATOS = {
    "nombre": "Paola Fabiana",
    "apellido": "Veron",
    "documento": "24470091",
    "unidad": "Unidad 16, PEREZ",
    "menores": "0"
}

def calcular_proximo_miercoles():
    hoy = datetime.now()
    dias_hasta_miercoles = (2 - hoy.weekday()) % 7
    if dias_hasta_miercoles == 0:
        dias_hasta_miercoles = 7
    proximo_miercoles = hoy + timedelta(days=dias_hasta_miercoles)
    return proximo_miercoles

async def run():
    downloads_path = Path(__file__).parent / "downloads"
    downloads_path.mkdir(exist_ok=True)
    
    fecha_visita = calcular_proximo_miercoles()
    print(f"Fecha de visita calculada: {fecha_visita.strftime('%d/%m/%Y')}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        
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
        
        print(f"Seleccionando fecha: {fecha_visita.strftime('%d/%m/%Y')}")
        date_input = page.locator("input[type='date']")
        fecha_formato_input = fecha_visita.strftime("%Y-%m-%d")
        await date_input.fill(fecha_formato_input)
        
        print(f"Llenando documento: {DATOS['documento']}")
        documento_input = page.get_by_placeholder("DOCUMENTO*")
        await documento_input.fill(DATOS["documento"])
        
        print(f"Seleccionando menores: {DATOS['menores']}")
        menores_select = page.locator("select").nth(1)
        await menores_select.select_option(value=DATOS["menores"])
        
        print("Haciendo clic en GENERAR TURNO...")
        print("NOTA: El captcha no se completa automaticamente, el servidor rechazara la solicitud.")
        
        generar_btn = page.get_by_role("button", name="Generar Turno")
        
        try:
            async with page.expect_download(timeout=10000) as download_info:
                await generar_btn.click()
            download = await download_info.value
            pdf_path = downloads_path / f"turno_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            await download.save_as(pdf_path)
            print(f"PDF guardado en: {pdf_path}")
        except Exception as e:
            print(f"No se pudo descargar el PDF (esperado sin captcha): {e}")
            screenshot_path = downloads_path / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await page.screenshot(path=str(screenshot_path))
            print(f"Screenshot guardado en: {screenshot_path}")
            pdf_path = None
        
        await browser.close()
        
    return str(pdf_path) if pdf_path else None

async def main():
    try:
        result = await run()
        if result:
            print(f"Proceso completado. PDF: {result}")
        else:
            print("Proceso completado sin PDF (captcha requerido)")
    except Exception as e:
        print(f"Error durante la ejecucion: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
