"""In-app help: getting started (written for each role), keyboard shortcuts, and credits."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from html import escape

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from servesync import __app_name__, __version__
from servesync.core.i18n import Language, current_language, format_clock, tr
from servesync.models import UserRole
from servesync.ui.widgets.common import make_label

LEADER_GUIDE = """
<h2>Getting started</h2>
<p>ServeSync helps you recruit volunteers, plan programs, fill shifts, and keep an honest record of service.</p>
<h3>Every day</h3>
<ul>
<li><b>Dashboard</b> shows what needs you: applicants to review and shifts that still need people this week.</li>
<li>Open any shift to see its roster. Before it starts, sign people up; once it starts, record attendance.</li>
</ul>
<h3>Recruiting</h3>
<ul>
<li>Choose <b>Add volunteer</b> (top right) to register someone. New people start as <i>Applicants</i>.</li>
<li>On <b>Volunteers</b>, select an applicant and choose <b>Approve</b> once they've completed orientation.</li>
<li>Archive people who step away; their service history is always kept.</li>
</ul>
<h3>Programs and shifts</h3>
<ul>
<li>On <b>Programs</b>, create a program, then add shifts. Use <i>Repeat weekly</i> for recurring work.</li>
<li>Programs start as drafts. Choose <b>Publish</b> so volunteers can see and join them.</li>
<li>Add your own program photo and a story video link to help volunteers feel the impact.</li>
</ul>
<h3>Reports</h3>
<ul>
<li>On <b>Reports</b>, pick a question (volunteer hours, program impact, shift attendance, recruitment,
or one person's service record), a period, and optionally a program or category.</li>
<li>Read <i>What stands out</i> for plain-English findings, choose <b>Columns</b> to show more detail,
then <b>Export CSV</b> or <b>Save PDF</b>. Exports contain exactly what you see.</li>
</ul>
<h3>Ask ServeSync</h3>
<ul>
<li>Press <b>Ctrl+K</b> (or choose <b>Ask</b> at the top) and type a question such as
<i>Who is free Saturday morning?</i> or <i>How is the food pantry doing?</i></li>
<li>Type a page name instead to jump straight there. Answers come only from this computer's records.</li>
</ul>
<h3>Smart Match</h3>
<ul>
<li>In a shift, open the <b>Smart Match</b> tab to see the best available volunteers, ranked 0 to 100.</li>
<li>Each colored bar shows the five reasons behind the score: availability, skills, reliability,
experience, and fair share. Marks with ! are things to double-check.</li>
<li>Smart Match never suggests anyone who is too young, already booked, or not yet approved.</li>
<li>If a program doesn't list support for someone's access needs (for example, step-free entry), they appear
after everyone else with a note saying why. Nobody is ever hidden or refused because of an access need.</li>
</ul>
"""

VOLUNTEER_GUIDE = """
<h2>Getting started</h2>
<p>Welcome! Here's how to find ways to help and keep track of your service.</p>
<ul>
<li><b>Home</b> shows your upcoming shifts, your hours, and shifts picked for you by Smart Match.</li>
<li>Choose <b>Find a shift</b> (top right) to browse everything that's open. Select a shift to see details,
then choose <b>Sign up</b>. If you can't sign up, ServeSync tells you why.</li>
<li><b>Calendar</b> shows every open shift by date.</li>
<li>Need to cancel? Select the shift on <b>Home</b> and choose <b>Cancel sign-up</b>, any time before it starts.</li>
<li>Keep your availability and skills current on <b>My profile</b> so recommendations fit your life.
You can also add the name you go by, your pronouns, and any access needs (step-free entry, seated tasks,
public transit, a quiet space, no cost, or remote).</li>
<li><b>My hours</b> lists your verified service. Choose <b>Save PDF</b> for school, scholarships, or employers.</li>
<li>Press <b>Ctrl+K</b> and ask things like <i>When is my next shift?</i> or <i>What should I sign up for?</i></li>
</ul>
"""

SHORTCUTS = """
<h2>Keyboard shortcuts</h2>
<p>Everything in ServeSync works from the keyboard. On a Mac, use Command where you see Ctrl.</p>
<table cellpadding="6">
<tr><td><b>Ctrl+K</b></td><td>Ask ServeSync a question, or type a page name to go there</td></tr>
<tr><td><b>Ctrl+1 ... Ctrl+6</b></td><td>Go to each page, in order</td></tr>
<tr><td><b>Ctrl+N</b></td><td>The main action at the top right (Add volunteer, or Find a shift)</td></tr>
<tr><td><b>Ctrl+F</b></td><td>Jump to the search box on the current page</td></tr>
<tr><td><b>Ctrl+= / Ctrl+- / Ctrl+0</b></td><td>Larger text, smaller text, normal size (saved for you)</td></tr>
<tr><td><b>Ctrl+Shift+H</b></td><td>High contrast on or off</td></tr>
<tr><td><b>Arrow keys</b></td><td>On a chart: move between bars or points; each value is read aloud</td></tr>
<tr><td><b>F1</b></td><td>Open this help</td></tr>
<tr><td><b>Tab / Shift+Tab</b></td><td>Move between controls (the focused control has a blue outline)</td></tr>
<tr><td><b>Enter</b></td><td>Open the selected row, or press the highlighted button</td></tr>
<tr><td><b>Esc</b></td><td>Close a window without saving</td></tr>
</table>
<h3>Comfort and accessibility</h3>
<p>Go to <b>Settings</b> to choose a theme (Match my computer, Light, Dark, or High contrast), make text up to
twice as large, add extra letter spacing, reduce motion, simplify the layout, and choose how long messages stay
on screen, and switch the language. Your choices follow your account to any computer. Missed a message? See
<b>Help &gt; Recent messages</b>.</p>
"""

ABOUT = f"""
<h2>About {__app_name__}</h2>
<p>Version {__version__}. Volunteer management for nonprofits, built for the
FBLA Coding &amp; Programming event (2026-2027).</p>
<h3>Credits</h3>
<ul>
<li>Fonts: Atkinson Hyperlegible (Braille Institute of America) and Source Serif 4 (Adobe),
both under the SIL Open Font License 1.1.</li>
<li>Icons: Lucide, ISC License.</li>
<li>Interface toolkit: Qt for Python (PySide6), LGPL v3.</li>
<li>Value of a volunteer hour: Independent Sector and the Do Good Institute, University of
Maryland, April 2026 ($36.14 national estimate).</li>
</ul>
<p>Demo people, places, and organizations are fictional.</p>
"""


# ---------------------------------------------------------------- Español

LEADER_GUIDE_ES = """
<h2>Primeros pasos</h2>
<p>ServeSync le ayuda a reclutar voluntarios, planificar programas, cubrir turnos y llevar un registro fiel
del servicio.</p>
<h3>Todos los días</h3>
<ul>
<li>El <b>Panel</b> muestra lo que necesita su atención: solicitantes por revisar y turnos de esta semana que aún
necesitan personas.</li>
<li>Abra cualquier turno para ver su lista. Antes de que empiece, inscriba a las personas; cuando empiece, registre
la asistencia.</li>
</ul>
<h3>Reclutamiento</h3>
<ul>
<li>Elija <b>Agregar voluntario</b> (arriba a la derecha) para registrar a alguien. Las personas nuevas empiezan como
<i>Solicitantes</i>.</li>
<li>En <b>Voluntarios</b>, seleccione a un solicitante y elija <b>Aprobar</b> cuando haya completado
la orientación.</li>
<li>Archive a quienes se retiren; su historial de servicio siempre se conserva.</li>
</ul>
<h3>Programas y turnos</h3>
<ul>
<li>En <b>Programas</b>, cree un programa y luego agregue turnos. Use <i>Repetir cada semana</i> para el trabajo
recurrente.</li>
<li>Los programas empiezan como borradores. Elija <b>Publicar</b> para que los voluntarios puedan verlos e
inscribirse.</li>
<li>Agregue su propia foto del programa y un enlace a un video para que los voluntarios sientan el impacto.</li>
</ul>
<h3>Informes</h3>
<ul>
<li>En <b>Informes</b>, elija una pregunta (horas de voluntariado, impacto del programa, asistencia a turnos,
reclutamiento o el historial de servicio de una persona), un período y, si quiere, un programa o una categoría.</li>
<li>Lea <i>Lo más destacado</i> para ver los hallazgos en lenguaje sencillo, elija <b>Columnas</b> para ver más
detalle y luego <b>Exportar CSV</b> o <b>Guardar PDF</b>. Lo que exporta es exactamente lo que ve.</li>
</ul>
<h3>Pregúntale a ServeSync</h3>
<ul>
<li>Presione <b>Ctrl+K</b> (o elija <b>Preguntar</b> arriba) y escriba una pregunta como
<i>¿Quién está libre el sábado por la mañana?</i> o <i>¿Cómo va la despensa de alimentos?</i></li>
<li>También puede escribir el nombre de una página para ir directamente. Las respuestas salen solo de los registros
de esta computadora.</li>
</ul>
<h3>Smart Match</h3>
<ul>
<li>En un turno, abra la pestaña <b>Smart Match</b> para ver a los mejores voluntarios disponibles, con una
puntuación de 0 a 100.</li>
<li>Cada barra de color muestra las cinco razones de la puntuación: disponibilidad, habilidades, confiabilidad,
experiencia y reparto justo. Las marcas con ! son cosas que conviene verificar.</li>
<li>Smart Match nunca sugiere a nadie que sea demasiado joven, que ya tenga otro turno o que aún no esté aprobado.</li>
<li>Si un programa no ofrece apoyo para las necesidades de acceso de alguien (por ejemplo, entrada sin escalones),
esa persona aparece después de los demás con una nota que explica por qué. Nadie se oculta ni se rechaza nunca por
una necesidad de acceso.</li>
</ul>
"""

VOLUNTEER_GUIDE_ES = """
<h2>Primeros pasos</h2>
<p>¡Bienvenido! Así puede encontrar formas de ayudar y llevar el control de su servicio.</p>
<ul>
<li><b>Inicio</b> muestra sus próximos turnos, sus horas y los turnos que Smart Match eligió para usted.</li>
<li>Elija <b>Buscar un turno</b> (arriba a la derecha) para ver todo lo que está abierto. Seleccione un turno para ver
los detalles y luego elija <b>Inscribirme</b>. Si no puede inscribirse, ServeSync le dice por qué.</li>
<li><b>Calendario</b> muestra cada turno abierto por fecha.</li>
<li>¿Necesita cancelar? Seleccione el turno en <b>Inicio</b> y elija <b>Cancelar inscripción</b> en cualquier
momento antes de que empiece.</li>
<li>Mantenga al día su disponibilidad y sus habilidades en <b>Mi perfil</b> para que las recomendaciones se ajusten a
su vida. También puede agregar el nombre que usa, sus pronombres y cualquier necesidad de acceso (entrada sin
escalones, tareas sentado, transporte público, un espacio tranquilo, sin costo o a distancia).</li>
<li><b>Mis horas</b> enumera su servicio verificado. Elija <b>Guardar PDF</b> para la escuela, becas o empleadores.</li>
<li>Presione <b>Ctrl+K</b> y pregunte cosas como <i>¿Cuándo es mi próximo turno?</i> o
<i>¿En qué debería inscribirme?</i></li>
</ul>
"""

SHORTCUTS_ES = """
<h2>Atajos de teclado</h2>
<p>Todo en ServeSync funciona con el teclado. En una Mac, use Comando donde vea Ctrl.</p>
<table cellpadding="6">
<tr><td><b>Ctrl+K</b></td><td>Hacerle una pregunta a ServeSync, o escribir el nombre de una página
para ir allí</td></tr>
<tr><td><b>Ctrl+1 ... Ctrl+6</b></td><td>Ir a cada página, en orden</td></tr>
<tr><td><b>Ctrl+N</b></td><td>La acción principal arriba a la derecha (Agregar voluntario o Buscar un turno)</td></tr>
<tr><td><b>Ctrl+F</b></td><td>Ir al cuadro de búsqueda de la página actual</td></tr>
<tr><td><b>Ctrl+= / Ctrl+- / Ctrl+0</b></td><td>Texto más grande, más pequeño o tamaño normal (se guarda para
usted)</td></tr>
<tr><td><b>Ctrl+Shift+H</b></td><td>Activar o desactivar el alto contraste</td></tr>
<tr><td><b>Teclas de flecha</b></td><td>En un gráfico: moverse entre barras o puntos; cada valor se lee en voz
alta</td></tr>
<tr><td><b>F1</b></td><td>Abrir esta ayuda</td></tr>
<tr><td><b>Tab / Shift+Tab</b></td><td>Moverse entre controles (el control activo tiene un contorno azul)</td></tr>
<tr><td><b>Enter</b></td><td>Abrir la fila seleccionada o presionar el botón resaltado</td></tr>
<tr><td><b>Esc</b></td><td>Cerrar una ventana sin guardar</td></tr>
</table>
<h3>Comodidad y accesibilidad</h3>
<p>Vaya a <b>Configuración</b> para elegir un tema (Igual que mi computadora, Claro, Oscuro o Alto contraste), hacer el
texto hasta el doble de grande, agregar más espacio entre letras, reducir el movimiento, simplificar el diseño, elegir
cuánto tiempo se muestran los mensajes y cambiar el idioma. Sus preferencias le siguen a cualquier computadora.
¿Se perdió un mensaje? Vea <b>Ayuda &gt; Mensajes recientes</b>.</p>
"""

ABOUT_ES = f"""
<h2>Acerca de {__app_name__}</h2>
<p>Versión {__version__}. Gestión de voluntarios para organizaciones sin fines de lucro, creada para la competencia
FBLA Coding &amp; Programming (2026-2027).</p>
<h3>Créditos</h3>
<ul>
<li>Fuentes: Atkinson Hyperlegible (Braille Institute of America) y Source Serif 4 (Adobe),
ambas bajo la SIL Open Font License 1.1.</li>
<li>Íconos: Lucide, licencia ISC.</li>
<li>Herramientas de interfaz: Qt for Python (PySide6), LGPL v3.</li>
<li>Valor de una hora de voluntariado: Independent Sector y el Do Good Institute, Universidad de
Maryland, abril de 2026 (estimación nacional de $36.14).</li>
<li>Traducción al español: equipo de ServeSync.</li>
</ul>
<p>Las personas, los lugares y las organizaciones de la demostración son ficticios.</p>
"""


def _pages(role: UserRole) -> tuple[str, str, str]:
    """The guide, shortcuts and about pages in the current language."""
    if current_language() is Language.SPANISH:
        return (LEADER_GUIDE_ES if role.is_leader else VOLUNTEER_GUIDE_ES, SHORTCUTS_ES, ABOUT_ES)
    return (LEADER_GUIDE if role.is_leader else VOLUNTEER_GUIDE, SHORTCUTS, ABOUT)


class HelpDialog(QDialog):
    def __init__(self, role: UserRole, parent: QWidget | None = None, *, start_tab: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ServeSync help"))
        self.resize(720, 620)
        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 16)
        column.addWidget(make_label(tr("Help"), "title"))
        tabs = QTabWidget()
        guide, shortcuts, about = _pages(role)
        for title, html in (
            (tr("Getting started"), guide),
            (tr("Keyboard shortcuts"), shortcuts),
            (tr("About"), about),
        ):
            browser = QTextBrowser()
            browser.setOpenExternalLinks(False)
            browser.setHtml(html)
            browser.setAccessibleName(title)
            tabs.addTab(browser, title)
        tabs.setCurrentIndex(start_tab)
        column.addWidget(tabs, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        column.addWidget(close)


class RecentMessagesDialog(QDialog):
    """The last confirmations, for anyone who missed a message before it closed (WCAG 2.2.1)."""

    def __init__(self, history: Sequence[tuple[datetime, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Recent messages"))
        self.resize(560, 420)
        column = QVBoxLayout(self)
        column.setContentsMargins(20, 18, 20, 16)
        column.addWidget(make_label(tr("Recent messages"), "title"))
        browser = QTextBrowser()
        browser.setAccessibleName(tr("Recent messages, newest first"))
        if history:
            items = "".join(
                f"<li><b>{format_clock(moment)}</b> \u2014 {escape(text)}</li>" for moment, text in reversed(history)
            )
            browser.setHtml(f"<ul>{items}</ul>")
        else:
            browser.setHtml(f"<p>{escape(tr('No messages yet.'))}</p>")
        column.addWidget(browser, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        column.addWidget(close)
