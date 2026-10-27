"""
How-to answers for "How do I...?" questions, found by keyword retrieval.

Each article is short (two to four steps), names the exact button to press,
and can carry an action that opens the right page. Retrieval scores each
article by the question's stemmed words, weighted so rare, specific words
("pronouns", "export") count more than common ones ("volunteer") — the idea
behind search engines' TF-IDF ranking, in a few lines.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from servesync.core.i18n import Language, current_language
from servesync.services.assistant.language import STOPWORDS, stems


@dataclass(frozen=True, slots=True)
class HelpArticle:
    title: str
    keywords: str  # extra words people use for this topic
    steps: tuple[str, ...]
    page: str = ""  # page key the answer can open
    leaders_only: bool = False
    action_label: str = ""


ARTICLES: tuple[HelpArticle, ...] = (
    HelpArticle(
        "Add a new volunteer",
        "register new person sign up recruit enroll create volunteer",
        (
            "Choose Add volunteer at the top right (or press Ctrl+N).",
            "Fill in the form; anything that needs fixing is explained beside the field.",
            "New people start as Applicants until you approve them.",
        ),
        "volunteers",
        True,
        "Open Volunteers",
    ),
    HelpArticle(
        "Approve an applicant",
        "approve applicant accept activate onboard orientation pending review",
        (
            "Open Volunteers and filter Status to Applicant.",
            "Select the person, then choose Approve.",
            "Approved volunteers can be scheduled right away.",
        ),
        "volunteers",
        True,
        "Open Volunteers",
    ),
    HelpArticle(
        "Create a program and its shifts",
        "program opportunity event project create new add shift shifts schedule repeat weekly every week recurring",
        (
            "Open Programs and choose New program.",
            "With the program selected, choose Add shift; tick Repeat weekly for recurring work.",
            "Programs start as drafts. Choose Publish so volunteers can see them.",
        ),
        "programs",
        True,
        "Open Programs",
    ),
    HelpArticle(
        "Sign someone up for a shift",
        "assign schedule book roster add person shift sign up volunteer",
        (
            "Open the shift from the Calendar or Programs page.",
            "On the Roster tab choose Add volunteer, or use the Smart Match tab for ranked suggestions.",
        ),
        "calendar",
        True,
        "Open Calendar",
    ),
    HelpArticle(
        "Record attendance and hours",
        "attendance check in hours served no show record log present absent",
        (
            "Open the shift once it has started.",
            "On the Roster tab mark each person Attended (with hours) or No-show.",
            "Hours count toward reports and service records as soon as they're saved.",
        ),
        "calendar",
        True,
        "Open Calendar",
    ),
    HelpArticle(
        "How Smart Match works",
        "smart match score recommend ranking points why explain algorithm factors",
        (
            "Smart Match scores each eligible person from 0 to 100 using five factors: availability (30), "
            "skills (30), reliability (20), experience (10), and fair share (10).",
            "Anyone too young, not yet approved, already booked, or double-booked is never suggested.",
            "People whose access needs a program doesn't list are shown last, with the reason — never hidden.",
        ),
    ),
    HelpArticle(
        "Run and export a report",
        "report export csv pdf excel spreadsheet print analysis data chart download customize",
        (
            "Open Reports and pick a question, a period, and optionally a program.",
            "Choose Columns to show or hide details, and click a heading to sort.",
            "Export CSV for spreadsheets or Save PDF for a printable copy; both contain exactly what you see.",
        ),
        "reports",
        True,
        "Open Reports",
    ),
    HelpArticle(
        "Get a service hours record",
        "service hours record letter certificate school scholarship verification proof community service pdf",
        (
            "Volunteers: open My hours and choose Save PDF.",
            "Leaders: open Reports, choose Service hours record, and pick the volunteer.",
            "The record lists each shift, the program, and hours, with a line for a coordinator's signature.",
        ),
        "hours",
    ),
    HelpArticle(
        "Find and sign up for a shift",
        "find shift sign up join browse open opportunity volunteer myself",
        (
            "Choose Find a shift at the top right.",
            "Shifts that fit your availability, skills, and access needs come first, with a Fit score.",
            "Select a shift and choose Sign up. If you can't, ServeSync explains why.",
        ),
        "find",
    ),
    HelpArticle(
        "Cancel a sign-up",
        "cancel drop withdraw remove can not make it sick sign up",
        (
            "On Home, select the upcoming shift and choose Cancel sign-up (any time before it starts).",
            "Your spot opens for someone else and the record is kept honestly as cancelled.",
        ),
        "home",
    ),
    HelpArticle(
        "Make the screen easier to use",
        "accessibility text size bigger font larger dark mode high contrast theme motion animation spacing "
        "dyslexia simplified layout low vision color blind screen reader messages timing",
        (
            "Open Settings, then Comfort and accessibility.",
            "Choose a theme (including High contrast or Match my computer), text up to 200%, extra letter spacing, "
            "reduced motion, a simplified layout, and how long messages stay up.",
            "Your choices follow your account to any computer.",
        ),
        "settings",
    ),
    HelpArticle(
        "Keyboard shortcuts",
        "keyboard shortcut keys hotkey mouse navigate tab without mouse",
        (
            "Ctrl+1 to Ctrl+6 open each page; Ctrl+K opens Ask ServeSync; Ctrl+N is the main action.",
            "Ctrl+F jumps to search; F1 opens help; Tab moves between controls; Esc closes a window.",
            "On a Mac, use Command where you see Ctrl.",
        ),
    ),
    HelpArticle(
        "Access needs and accommodations",
        "access need accommodation wheelchair step free disability transit bus seated quiet sensory remote "
        "cost money cannot afford",
        (
            "Volunteers can list access needs on My profile (step-free, seated tasks, transit, quiet space, "
            "no cost, or remote).",
            "Programs list what they offer on the program form.",
            "ServeSync never blocks anyone for an access need; it shows the gap so people can decide or ask.",
        ),
        "profile",
    ),
    HelpArticle(
        "Names and pronouns",
        "preferred name nickname pronouns she he they chosen name gender",
        (
            "A volunteer's profile has optional 'Name they go by' and 'Pronouns' fields.",
            "The name they go by is shown everywhere; the legal name appears only on safety records "
            "and service hours records.",
            "Pronouns are shown only if the person shares them; ServeSync never guesses.",
        ),
    ),
    HelpArticle(
        "Young volunteers",
        "minor teen age young under 18 child student parent guardian youth",
        (
            "Volunteers must be at least 14. Anyone under 18 needs a parent or guardian as emergency contact.",
            "A program can set a higher minimum age; younger volunteers are never matched to it.",
        ),
    ),
    HelpArticle(
        "Is my data safe?",
        "data privacy safe secure backup password security offline internet cloud",
        (
            "Everything stays on this computer in one file; nothing is sent over the internet.",
            "Passwords are stored as salted PBKDF2 hashes (600,000 rounds), and 5 wrong tries lock an account "
            "for 15 minutes.",
            "To back up, copy the ServeSync data folder shown in Settings.",
        ),
    ),
)


#: Spanish versions, in the same order as ARTICLES (pages and audiences are shared).
_SPANISH: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "Agregar un voluntario nuevo",
        "registrar persona nueva inscribir reclutar alta crear voluntario agregar",
        (
            "Elija Agregar voluntario arriba a la derecha (o presione Ctrl+N).",
            "Llene el formulario; todo lo que haya que corregir se explica junto al campo.",
            "Las personas nuevas empiezan como Solicitantes hasta que usted las aprueba.",
        ),
        "Abrir Voluntarios",
    ),
    (
        "Aprobar a un solicitante",
        "aprobar solicitante aceptar activar orientacion pendiente revisar solicitud",
        (
            "Abra Voluntarios y filtre el Estado por Solicitante.",
            "Seleccione a la persona y elija Aprobar.",
            "Los voluntarios aprobados se pueden programar de inmediato.",
        ),
        "Abrir Voluntarios",
    ),
    (
        "Crear un programa y sus turnos",
        "programa oportunidad evento proyecto crear nuevo agregar turno turnos horario repetir semanal cada semana",
        (
            "Abra Programas y elija Nuevo programa.",
            "Con el programa seleccionado, elija Agregar turnos; marque Repetir cada semana para el trabajo "
            "recurrente.",
            "Los programas empiezan como borradores. Elija Publicar para que los voluntarios los vean.",
        ),
        "Abrir Programas",
    ),
    (
        "Inscribir a alguien en un turno",
        "asignar programar reservar lista agregar persona turno inscribir voluntario",
        (
            "Abra el turno desde la página Calendario o Programas.",
            "En la pestaña Lista elija Agregar voluntario, o use la pestaña Smart Match para ver sugerencias "
            "ordenadas.",
        ),
        "Abrir Calendario",
    ),
    (
        "Registrar asistencia y horas",
        "asistencia registrar entrada horas servidas no se presento presente ausente",
        (
            "Abra el turno cuando haya empezado.",
            "En la pestaña Lista marque a cada persona como Asistió (con sus horas) o No se presentó.",
            "Las horas cuentan para los informes y los historiales de servicio en cuanto se guardan.",
        ),
        "Abrir Calendario",
    ),
    (
        "Cómo funciona Smart Match",
        "smart match puntuacion recomendar clasificacion puntos por que explicar algoritmo factores",
        (
            "Smart Match puntúa de 0 a 100 a cada persona elegible con cinco factores: disponibilidad (30), "
            "habilidades (30), confiabilidad (20), experiencia (10) y reparto justo (10).",
            "Nunca se sugiere a nadie demasiado joven, sin aprobar, ya inscrito o con otro turno a la misma hora.",
            "Las personas cuyas necesidades de acceso un programa no ofrece aparecen al final, con la razón; "
            "nunca se ocultan.",
        ),
        "",
    ),
    (
        "Crear y exportar un informe",
        "informe reporte exportar csv pdf excel hoja de calculo imprimir analisis datos grafico descargar",
        (
            "Abra Informes y elija una pregunta, un período y, si quiere, un programa.",
            "Elija Columnas para mostrar u ocultar detalles, y haga clic en un encabezado para ordenar.",
            "Exportar CSV sirve para hojas de cálculo y Guardar PDF para una copia impresa; ambos contienen "
            "exactamente lo que ve.",
        ),
        "Abrir Informes",
    ),
    (
        "Obtener un historial de horas de servicio",
        "historial horas servicio constancia carta certificado escuela beca verificacion comprobante "
        "servicio comunitario pdf",
        (
            "Voluntarios: abran Mis horas y elijan Guardar PDF.",
            "Líderes: abran Informes, elijan Historial de horas de servicio y seleccionen al voluntario.",
            "El historial enumera cada turno, el programa y las horas, con una línea para la firma de un coordinador.",
        ),
        "",
    ),
    (
        "Buscar un turno e inscribirse",
        "buscar turno inscribirme unirme explorar abierto oportunidad voluntariado",
        (
            "Elija Buscar un turno arriba a la derecha.",
            "Los turnos que se ajustan a su disponibilidad, habilidades y necesidades de acceso aparecen primero, "
            "con una puntuación de ajuste.",
            "Seleccione un turno y elija Inscribirme. Si no puede, ServeSync le explica por qué.",
        ),
        "",
    ),
    (
        "Cancelar una inscripción",
        "cancelar dejar retirar quitar no puedo ir enfermo inscripcion",
        (
            "En Inicio, seleccione el próximo turno y elija Cancelar inscripción (en cualquier momento antes de "
            "que empiece).",
            "Su lugar queda libre para otra persona y el registro se guarda tal cual, como cancelado.",
        ),
        "",
    ),
    (
        "Hacer la pantalla más fácil de usar",
        "accesibilidad tamano texto letra grande fuente modo oscuro alto contraste tema movimiento animacion "
        "espaciado dislexia diseno simplificado baja vision daltonismo lector de pantalla mensajes idioma "
        "espanol ingles",
        (
            "Abra Configuración y luego Comodidad y accesibilidad.",
            "Elija un tema (incluidos Alto contraste e Igual que mi computadora), texto hasta 200 %, más espacio "
            "entre letras, menos movimiento, un diseño simplificado, cuánto tiempo se muestran los mensajes y "
            "el idioma.",
            "Sus preferencias le siguen a cualquier computadora.",
        ),
        "",
    ),
    (
        "Atajos de teclado",
        "teclado atajo teclas raton navegar tab sin raton",
        (
            "Ctrl+1 a Ctrl+6 abren cada página; Ctrl+K abre Pregúntale a ServeSync; Ctrl+N es la acción principal.",
            "Ctrl+F va a la búsqueda; F1 abre la ayuda; Tab pasa de un control a otro; Esc cierra una ventana.",
            "En una Mac, use Comando donde vea Ctrl.",
        ),
        "",
    ),
    (
        "Necesidades de acceso y adaptaciones",
        "acceso necesidad adaptacion silla de ruedas sin escalones discapacidad transporte autobus sentado "
        "tranquilo sensorial a distancia costo dinero no puedo pagar",
        (
            "Los voluntarios pueden indicar sus necesidades de acceso en Mi perfil (sin escalones, tareas sentado, "
            "transporte, espacio tranquilo, sin costo o a distancia).",
            "Los programas indican lo que ofrecen en el formulario del programa.",
            "ServeSync nunca bloquea a nadie por una necesidad de acceso; muestra lo que falta para que la "
            "persona decida o pregunte.",
        ),
        "",
    ),
    (
        "Nombres y pronombres",
        "nombre preferido apodo pronombres ella el elle nombre elegido genero",
        (
            "El perfil de cada voluntario tiene los campos opcionales 'Nombre que usa' y 'Pronombres'.",
            "El nombre que usa aparece en todas partes; el nombre legal solo aparece en los registros de "
            "seguridad y en los historiales de horas de servicio.",
            "Los pronombres solo se muestran si la persona los comparte; ServeSync nunca los adivina.",
        ),
        "",
    ),
    (
        "Voluntarios jóvenes",
        "menor adolescente edad joven menos de 18 nino estudiante padre madre tutor juventud",
        (
            "Los voluntarios deben tener al menos 14 años. Quien tenga menos de 18 necesita a su padre, madre o "
            "tutor como contacto de emergencia.",
            "Un programa puede fijar una edad mínima mayor; nunca se asigna a voluntarios más jóvenes.",
        ),
        "",
    ),
    (
        "¿Mis datos están seguros?",
        "datos privacidad seguro seguridad copia de respaldo contrasena sin conexion internet nube",
        (
            "Todo se queda en esta computadora, en un solo archivo; nada se envía por internet.",
            "Las contraseñas se guardan como hashes PBKDF2 con sal (600 000 rondas), y 5 intentos fallidos "
            "bloquean una cuenta durante 15 minutos.",
            "Para hacer una copia de respaldo, copie la carpeta de datos de ServeSync que aparece en Configuración.",
        ),
        "",
    ),
)

ARTICLES_ES: tuple[HelpArticle, ...] = tuple(
    replace(english, title=title, keywords=keywords, steps=steps, action_label=action)
    for english, (title, keywords, steps, action) in zip(ARTICLES, _SPANISH, strict=True)
)


@dataclass(frozen=True, slots=True)
class _Indexed:
    article: HelpArticle
    terms: Counter[str]


def _index(articles: Sequence[HelpArticle]) -> tuple[list[_Indexed], dict[str, float]]:
    indexed = []
    document_frequency: Counter[str] = Counter()
    for article in articles:
        terms: Counter[str] = Counter()
        for weight, text in ((3, article.title), (2, article.keywords), (1, " ".join(article.steps))):
            for term in stems(text):
                if term not in STOPWORDS:
                    terms[term] += weight
        indexed.append(_Indexed(article, terms))
        document_frequency.update(set(terms))
    total = len(articles)
    idf = {term: math.log(1 + total / count) for term, count in document_frequency.items()}
    return indexed, idf


_INDEXES = {Language.ENGLISH: _index(ARTICLES), Language.SPANISH: _index(ARTICLES_ES)}


def search_help(question: str, *, is_leader: bool, limit: int = 3) -> list[tuple[float, HelpArticle]]:
    """Articles that best answer the question, highest relevance first (in the interface language)."""
    terms = [term for term in stems(question) if term not in STOPWORDS]
    index, idf = _INDEXES[current_language()]
    results = []
    for entry in index:
        if entry.article.leaders_only and not is_leader:
            continue
        score = sum(idf.get(term, 0.0) * min(entry.terms.get(term, 0), 3) for term in set(terms))
        if score > 0:
            results.append((round(score, 3), entry.article))
    results.sort(key=lambda pair: (-pair[0], pair[1].title))
    return results[:limit]
