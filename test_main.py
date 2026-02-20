import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")


# ─── Tests para calcular_proximo_miercoles ───────────────────────────────────

class TestCalcularProximoMiercoles:
    @patch("main.datetime")
    def test_desde_lunes_devuelve_miercoles_mismo_semana(self, mock_dt):
        # Lunes 2026-02-16
        fake_now = datetime(2026, 2, 16, 10, 0, 0, tzinfo=TIMEZONE)
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        from main import calcular_proximo_miercoles
        result = calcular_proximo_miercoles()
        assert result.weekday() == 2  # Miércoles
        assert result.day == 18

    @patch("main.datetime")
    def test_desde_miercoles_devuelve_proximo_miercoles(self, mock_dt):
        # Miércoles 2026-02-18
        fake_now = datetime(2026, 2, 18, 10, 0, 0, tzinfo=TIMEZONE)
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        from main import calcular_proximo_miercoles
        result = calcular_proximo_miercoles()
        assert result.weekday() == 2
        assert result.day == 25  # Siguiente miércoles, no el actual

    @patch("main.datetime")
    def test_desde_jueves_devuelve_miercoles_siguiente(self, mock_dt):
        # Jueves 2026-02-19
        fake_now = datetime(2026, 2, 19, 23, 58, 0, tzinfo=TIMEZONE)
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        from main import calcular_proximo_miercoles
        result = calcular_proximo_miercoles()
        assert result.weekday() == 2
        assert result.day == 25


# ─── Tests para navegar_con_reintentos ───────────────────────────────────────

class TestNavegarConReintentos:
    @pytest.mark.asyncio
    async def test_exito_primer_intento(self):
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock()

        from main import navegar_con_reintentos
        result = await navegar_con_reintentos(page, "https://example.com", max_reintentos=3)

        assert result is True
        assert page.goto.call_count == 1
        page.goto.assert_called_with(
            "https://example.com",
            wait_until="domcontentloaded",
            timeout=30000
        )

    @pytest.mark.asyncio
    async def test_exito_tercer_intento(self):
        page = AsyncMock()
        page.goto = AsyncMock(
            side_effect=[
                Exception("net::ERR_CONNECTION_RESET"),
                Exception("net::ERR_CONNECTION_RESET"),
                None,  # Éxito en el tercer intento
            ]
        )
        page.wait_for_selector = AsyncMock()

        from main import navegar_con_reintentos
        with patch("main.asyncio.sleep", new_callable=AsyncMock):
            result = await navegar_con_reintentos(page, "https://example.com", max_reintentos=3)

        assert result is True
        assert page.goto.call_count == 3

    @pytest.mark.asyncio
    async def test_falla_todos_los_intentos(self):
        page = AsyncMock()
        page.goto = AsyncMock(side_effect=Exception("net::ERR_CONNECTION_RESET"))
        page.wait_for_selector = AsyncMock()

        from main import navegar_con_reintentos
        with patch("main.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(Exception, match="No se pudo cargar la pagina"):
                await navegar_con_reintentos(page, "https://example.com", max_reintentos=3)

        assert page.goto.call_count == 3

    @pytest.mark.asyncio
    async def test_falla_selector_reintenta(self):
        """Si goto funciona pero el selector no aparece, debe reintentar."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=[
                Exception("Timeout waiting for selector"),
                None,  # Éxito
            ]
        )

        from main import navegar_con_reintentos
        with patch("main.asyncio.sleep", new_callable=AsyncMock):
            result = await navegar_con_reintentos(page, "https://example.com", max_reintentos=3)

        assert result is True
        assert page.goto.call_count == 2

    @pytest.mark.asyncio
    async def test_backoff_exponencial(self):
        page = AsyncMock()
        page.goto = AsyncMock(
            side_effect=[
                Exception("fail 1"),
                Exception("fail 2"),
                Exception("fail 3"),
                None,
            ]
        )
        page.wait_for_selector = AsyncMock()

        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        from main import navegar_con_reintentos
        with patch("main.asyncio.sleep", side_effect=mock_sleep):
            await navegar_con_reintentos(page, "https://example.com", max_reintentos=5)

        # Backoff: min(2^1, 15)=2, min(2^2, 15)=4, min(2^3, 15)=8
        assert sleep_calls == [2, 4, 8]


# ─── Tests para cargar_pagina_y_seleccionar_unidad ───────────────────────────

class TestCargarPaginaYSeleccionarUnidad:
    @pytest.mark.asyncio
    async def test_carga_y_selecciona(self):
        page = AsyncMock()
        mock_select = AsyncMock()
        mock_locator_result = MagicMock()
        mock_locator_result.first = mock_select
        page.locator = MagicMock(return_value=mock_locator_result)
        page.wait_for_timeout = AsyncMock()

        with patch("main.navegar_con_reintentos", new_callable=AsyncMock) as mock_nav:
            mock_nav.return_value = True
            from main import cargar_pagina_y_seleccionar_unidad
            await cargar_pagina_y_seleccionar_unidad(page)

        mock_nav.assert_called_once()
        mock_select.select_option.assert_called_once_with(value="Unidad 16, PEREZ")


# ─── Tests para preparar_formulario ──────────────────────────────────────────

class TestPrepararFormulario:
    @pytest.mark.asyncio
    async def test_llena_todos_los_campos(self):
        page = AsyncMock()
        fecha = datetime(2026, 2, 25, tzinfo=TIMEZONE)

        mock_nombre = AsyncMock()
        mock_apellido = AsyncMock()
        mock_doc = AsyncMock()
        mock_date = AsyncMock()
        mock_menores = AsyncMock()

        page.get_by_placeholder = MagicMock(side_effect=lambda p: {
            "Nombre*": mock_nombre,
            "Apellido*": mock_apellido,
            "DOCUMENTO*": mock_doc,
        }[p])

        page.locator = MagicMock(side_effect=lambda sel: {
            "input[type='date']": mock_date,
            "select": MagicMock(nth=MagicMock(return_value=mock_menores)),
        }.get(sel, MagicMock()))

        from main import preparar_formulario
        result = await preparar_formulario(page, fecha)

        assert result == "25/02/2026"
        mock_nombre.fill.assert_called_once_with("Paola Fabiana")
        mock_apellido.fill.assert_called_once_with("Veron")
        mock_doc.fill.assert_called_once_with("24470091")
        mock_date.fill.assert_called_once_with("2026-02-25")

    @pytest.mark.asyncio
    async def test_no_navega(self):
        """Verifica que preparar_formulario NO llama page.goto."""
        page = AsyncMock()
        fecha = datetime(2026, 2, 25, tzinfo=TIMEZONE)

        mock_input = AsyncMock()
        page.get_by_placeholder = MagicMock(return_value=mock_input)
        mock_locator = AsyncMock()
        mock_locator.nth = MagicMock(return_value=AsyncMock())
        page.locator = MagicMock(return_value=mock_locator)

        from main import preparar_formulario
        await preparar_formulario(page, fecha)

        page.goto.assert_not_called()


# ─── Tests para esperar_turnos_disponibles ───────────────────────────────────

class TestEsperarTurnosDisponibles:
    @pytest.mark.asyncio
    async def test_turnos_disponibles_primer_intento(self):
        page = AsyncMock()
        fecha = datetime(2026, 2, 25, tzinfo=TIMEZONE)

        mock_date_input = AsyncMock()
        mock_date_input.get_attribute = AsyncMock(return_value="2026-02-25")
        page.locator = MagicMock(return_value=mock_date_input)

        with patch("main.cargar_pagina_y_seleccionar_unidad", new_callable=AsyncMock):
            from main import esperar_turnos_disponibles
            result = await esperar_turnos_disponibles(page, fecha)

        assert result is True

    @pytest.mark.asyncio
    async def test_turnos_no_disponibles_luego_si(self):
        page = AsyncMock()
        fecha = datetime(2026, 2, 25, tzinfo=TIMEZONE)

        mock_date_input = AsyncMock()
        mock_date_input.get_attribute = AsyncMock(
            side_effect=["2026-02-18", "2026-02-18", "2026-02-25"]
        )
        page.locator = MagicMock(return_value=mock_date_input)

        with patch("main.cargar_pagina_y_seleccionar_unidad", new_callable=AsyncMock), \
             patch("main.asyncio.sleep", new_callable=AsyncMock):
            from main import esperar_turnos_disponibles
            result = await esperar_turnos_disponibles(page, fecha)

        assert result is True
        assert mock_date_input.get_attribute.call_count == 3

    @pytest.mark.asyncio
    async def test_max_none_es_valido(self):
        """Si max es None, se considera válido (sin restricción)."""
        page = AsyncMock()
        fecha = datetime(2026, 2, 25, tzinfo=TIMEZONE)

        mock_date_input = AsyncMock()
        mock_date_input.get_attribute = AsyncMock(return_value=None)
        page.locator = MagicMock(return_value=mock_date_input)

        with patch("main.cargar_pagina_y_seleccionar_unidad", new_callable=AsyncMock):
            from main import esperar_turnos_disponibles
            result = await esperar_turnos_disponibles(page, fecha)

        assert result is True


# ─── Tests para el flujo completo (sin doble navegación) ─────────────────────

class TestFlujoCompleto:
    @pytest.mark.asyncio
    async def test_no_hay_doble_navegacion(self):
        """
        Test CRITICO: verifica que entre esperar_turnos_disponibles y
        preparar_formulario NO se hace una segunda navegación.
        """
        goto_calls = []

        async def track_goto(*args, **kwargs):
            goto_calls.append({"args": args, "kwargs": kwargs})

        page = AsyncMock()
        page.goto = AsyncMock(side_effect=track_goto)
        page.wait_for_selector = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        mock_select = AsyncMock()
        mock_date_input = AsyncMock()
        mock_date_input.get_attribute = AsyncMock(return_value="2026-02-25")
        mock_input = AsyncMock()
        mock_menores = AsyncMock()

        def locator_side_effect(sel):
            if sel == "select":
                mock = MagicMock()
                mock.first = mock_select
                mock.nth = MagicMock(return_value=mock_menores)
                return mock
            elif sel == "input[type='date']":
                return mock_date_input
            return AsyncMock()

        page.locator = MagicMock(side_effect=locator_side_effect)
        page.get_by_placeholder = MagicMock(return_value=mock_input)
        page.get_by_role = MagicMock(return_value=AsyncMock())

        fecha = datetime(2026, 2, 25, tzinfo=TIMEZONE)

        from main import esperar_turnos_disponibles, preparar_formulario

        # Paso 1: esperar turnos
        await esperar_turnos_disponibles(page, fecha)
        nav_count_after_esperar = len(goto_calls)

        # Paso 2: preparar formulario (NO debe navegar)
        await preparar_formulario(page, fecha)
        nav_count_after_preparar = len(goto_calls)

        # Solo una navegación total (la de esperar_turnos_disponibles)
        assert nav_count_after_esperar == 1, \
            f"esperar_turnos debería hacer exactamente 1 navegación, hizo {nav_count_after_esperar}"
        assert nav_count_after_preparar == 1, \
            f"preparar_formulario NO debería navegar, pero se hicieron {nav_count_after_preparar - nav_count_after_esperar} navegaciones extra"


# ─── Tests para enviar_formulario_con_reintentos ─────────────────────────────

class TestEnviarFormularioConReintentos:
    @pytest.mark.asyncio
    async def test_reintento_basado_en_tiempo_no_en_conteo(self):
        """Verifica que los reintentos son por tiempo (TIMEOUT_TOTAL), no por conteo fijo."""
        from main import TIMEOUT_TOTAL
        assert TIMEOUT_TOTAL == 900, "TIMEOUT_TOTAL debe ser 15 minutos (900 segundos)"

    @pytest.mark.asyncio
    async def test_timeout_detiene_reintentos(self):
        """Verifica que se detiene cuando se agota el tiempo."""
        page = AsyncMock()
        downloads_path = MagicMock()
        fecha = datetime(2026, 2, 25, tzinfo=TIMEZONE)

        mock_btn = AsyncMock()
        page.get_by_role = MagicMock(return_value=mock_btn)
        page.screenshot = AsyncMock()

        # Simular que expect_download siempre falla
        async def always_fail_download(timeout=None):
            class FailCtx:
                async def __aenter__(self_inner):
                    raise Exception("Download failed")
                async def __aexit__(self_inner, *a):
                    pass
            return FailCtx()

        page.expect_download = always_fail_download

        # Simular que ya pasaron 900+ segundos
        call_count = 0
        def mock_time():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return 0  # inicio
            return 901  # ya paso el timeout

        with patch("main.cargar_pagina_y_seleccionar_unidad", new_callable=AsyncMock), \
             patch("main.preparar_formulario", new_callable=AsyncMock), \
             patch("main.asyncio.sleep", new_callable=AsyncMock), \
             patch("time.time", side_effect=mock_time):
            from main import enviar_formulario_con_reintentos
            result = await enviar_formulario_con_reintentos(page, downloads_path, fecha)

        assert result is None


# ─── Test de integración: verificar que wait_until no es networkidle ─────────

class TestConfiguracion:
    @pytest.mark.asyncio
    async def test_usa_domcontentloaded_no_networkidle(self):
        """Verifica que la navegación usa domcontentloaded en vez de networkidle."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock()

        from main import navegar_con_reintentos
        await navegar_con_reintentos(page, "https://example.com")

        call_kwargs = page.goto.call_args[1]
        assert call_kwargs["wait_until"] == "domcontentloaded", \
            f"Debe usar domcontentloaded, no {call_kwargs['wait_until']}"

    def test_max_reintentos_navegacion_es_5(self):
        from main import MAX_REINTENTOS_NAVEGACION
        assert MAX_REINTENTOS_NAVEGACION == 5

    def test_timeout_navegacion_es_30s(self):
        from main import TIMEOUT_NAVEGACION
        assert TIMEOUT_NAVEGACION == 30000
