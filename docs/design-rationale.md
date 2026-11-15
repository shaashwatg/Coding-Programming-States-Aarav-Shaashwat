# ServeSync design rationale

ServeSync is used for long stretches: a coordinator may have it open all day at a front desk,
and a volunteer may check it on a shared library computer. The design goal is an interface that
is calm to look at for hours, makes the next action obvious, and works for people with low
vision, color blindness, tremor, dyslexia, or limited English.

Every visual decision lives in one file, `servesync/ui/theme.py`. Screens ask for a color by
*meaning* (`primary`, `text_muted`, `attention_fill`) and never by hex value; a test fails if a
page, widget or dialog hard-codes a color.

![Dashboard](screenshots/dashboard.png)

## Color

Three colors, plus neutrals. Each color has one job, so its meaning stays clear.

| Color | Value | Job | Where it appears |
|---|---|---|---|
| Deep indigo | `#2F3E9E` | The working color | Navigation, the one filled button per screen, links, selected rows, keyboard focus |
| Warm amber | `#F2A93B` | Look here | "Needs attention" markers, calendar dots for open days, the active chart bar, badges |
| Emerald | `#0E9F6E` | Good news | Success messages, open spots, the Smart Match score, finished goals |

**Why these three.** Indigo reads as trustworthy and serious without the coldness of a
corporate blue, and it holds 9:1 contrast on white, so it can be both a button fill and link
text. Amber is indigo's warm complement, so a single amber mark stands out on an otherwise cool
screen without needing to be large. Emerald is the conventional "done" color, and keeping it
rare means a green number is worth reading.

**Rules that keep it calm.**

* Amber is never text on a light background (it measures under 2:1 on white). It is always a
  shape: a 4 px bar beside a figure, a calendar dot, a chart bar. When amber is a fill, the text
  on it is dark slate (7.8:1).
* Emerald is 3.4:1 on white, which is fine for a bar or a dot but too light for text. Text that
  should be emerald uses a deeper shade of the same hue, `#04553A`, which keeps the 7:1 the app
  meets everywhere.
* The brief's secondary text color `#5B6478` measures 5.6:1 on white. ServeSync's standard is
  7:1 (WCAG AAA), so secondary text is one step darker, `#454D61`.
* Errors stay red (`#8C2A1F`) and always come with a warning icon and words, never color alone.

**Neutrals.** A cool off-white canvas (`#F7F8FB`), white surfaces for tables and cards, slate
text (`#1E2433`), and hairline borders (`#E3E6EE`). The cool cast keeps white areas from looking
yellow under office lighting and avoids the cream and beige backgrounds common in generated
designs.

**Dark theme.** The canvas is `#14161F` and surfaces are `#1C1F2B`. The three brand colors
become lighter tints of the same hues (indigo `#AEB8F5`, amber `#F5C878`, emerald `#6EDBB0`),
so meaning carries over and every text color still reaches 7:1.

**High contrast theme.** Black, white and yellow with a 3 px cyan focus ring. People who choose
it need maximum contrast more than they need brand colors, so it keeps its own palette.

`tests/test_theme.py` computes every contrast ratio with the WCAG formula, for every theme:
text 7:1 on every background it can sit on, borders and focus rings 3:1, and button labels 7:1.

## Type

| Role | Font | Size (at 100%) |
|---|---|---|
| Page title | Manrope SemiBold | 1.6 x body |
| Section title | Manrope SemiBold | 1.2 x body |
| Body | Atkinson Hyperlegible | the person's chosen size |
| Caption | Atkinson Hyperlegible | 0.88 x body |

**Atkinson Hyperlegible** (Braille Institute) is used for everything people read. It was
designed so that easily confused characters (I, l and 1; O and 0; b and d) look different, which
helps readers with low vision and anyone scanning a roster quickly.

**Manrope** (SIL Open Font License) is used for headings and key figures. It is a plain, modern
sans-serif with open shapes, so it pairs with Atkinson without competing with it, and its numbers
are clear at large sizes. It replaces the earlier serif headings, which felt editorial rather than
like a tool.

Headings are sentence case. There are no all-caps or letter-spaced labels, because all caps are
slower to read, especially for people with dyslexia. The whole scale grows with the person's text
size (85% to 200%), so nothing clips.

## Layout

* **8 px grid.** Margins, gaps and padding are multiples of 8 (with a 4 px half step for a label
  and its hint). Content is left-aligned so the eye always returns to the same edge.
* **Flat surfaces.** Areas are separated by space and hairline borders. There are no gradients,
  glows or heavy shadows.
* **Cards only for objects.** A shift, a volunteer recommendation, or the featured event is a
  card (white, hairline border, 10 px corners). Everything else, such as "Shifts that need people"
  or "What stands out", is a plain section with a heading.
* **Key figures** sit in a row, each set off by a hairline on its left. A figure that needs
  action gets an amber bar instead, and screen readers hear "needs attention".
* **Corners.** 6 px on buttons and inputs, 10 px on cards and dialogs.
* **One filled button per screen.** In the main window, the header's action (*Add volunteer* for
  leaders, *Find a shift* for volunteers) is the only filled indigo button. Other actions are
  outlined; a dialog's single main action (Save, Sign in) is filled.
* **Sidebar.** Light, with the current page marked by an indigo bar and indigo text and icon.
* **Tables.** No zebra stripes; hairline dividers, 44 px rows (comfortable to read and a full
  touch target), and a soft indigo tint on hover and selection. When text is large, the table
  scrolls sideways rather than squeezing a column until its text is cut off.
* **Charts.** Indigo first, then amber, then emerald, on neutral gridlines. The bar or point
  being inspected turns amber. Values are printed on every bar, and each chart has a text summary
  and a matching table.
* **Ask ServeSync** looks like a search panel: a search box, then plain rows that pair each
  question with its answer, separated by hairlines. It deliberately avoids chat bubbles, because
  it looks up the organization's own records and should not suggest a person or general chatbot is
  replying.
* **Motion** only follows something the person did (a click, a key press): a page fades in, the
  sidebar marker slides to the new page. *Reduce motion* removes all of it.

What we avoided, and why: cream backgrounds, terracotta accents, serif display headings, sparkle
and magic-wand icons, emoji, purple-to-blue gradients, small labels above headings, pill chips,
middle dots or long dashes joining labels, arrows in button text, and marketing-style copy. They
are common in generated interfaces, and they add decoration without helping anyone finish a task.

## Two user journeys

### Volunteer: Priya, a college student who needs service hours

1. **Sign in.** The sign-in screen offers English or Español at the top, each written in its own
   language, so anyone can find theirs.
2. **Home.** Her hours, shifts completed and show-up rate are the first figures. Her hour goal
   shows a progress bar that turns emerald when she reaches it.
3. **Find a shift.** The header's one filled button opens *Find a shift*. Filters start with
   "Only shifts I can sign up for", so she never chooses a shift and then hits a rule. The *Fit*
   column is her Smart Match score.
4. **Sign up.** The details panel says in plain words whether she can sign up ("You can sign up
   for this shift.") or why not (too young, already booked, full). One click signs her up, and a
   short message confirms it without moving her focus.
5. **My hours.** Her service record can be saved as a PDF for school.

### Leader: Dana, the volunteer coordinator, on a Monday morning

1. **Dashboard.** Four figures; the ones that need action (applicants to review, open spots this
   week) carry an amber bar. Below them, the next event that still needs people.
2. **Review applicants.** One click opens the Volunteers page already filtered to applicants.
   *Approve* makes them active.
3. **Fill a shift.** From *Shifts that need people this week*, she opens a shift and runs Smart
   Match. Each candidate card shows an emerald score, a bar of where the points came from, and the
   reasons in words.
4. **Look ahead.** *Staffing Studio* drafts sign-ups for the next two weeks, forecasts turnout,
   and lists people who have quietly stopped coming. Nothing is saved until she approves.
5. **Report.** *Reports* answers a question for a period and saves exactly what is on screen as
   CSV or PDF.

## Accessibility features

| Need | What ServeSync does | WCAG |
|---|---|---|
| Low vision | 7:1 text contrast in every theme; High contrast theme; text 85% to 200% (Ctrl+= and Ctrl+-) with nothing clipped | 1.4.6, 1.4.4 |
| Finding controls | Input borders and focus rings at 3:1 or better; a 2 to 3 px focus outline on everything | 1.4.11, 2.4.13 |
| Motor and tremor | Every target at least 44 x 44 px, growing with text size | 2.5.5 |
| Keyboard only | Every action works without a mouse; charts respond to arrow keys; Ctrl+K reaches any page or answer | 2.1.3 |
| Screen readers | Accessible names on every control; changes announced without moving focus; charts have text summaries | 4.1.3, 1.1.1 |
| Motion sensitivity | Motion only follows the person's action; *Reduce motion* removes it | 2.3.3 |
| Dyslexia | Atkinson Hyperlegible; optional extra letter and word spacing; no all-caps text | 1.4.12, 1.4.8 |
| Attention and memory | *Simplified layout* hides secondary sections; one filled button per screen; plain-language messages | 3.1.5 |
| Color vision | Status always has words or a shape; errors have an icon; chart values are printed | 1.4.1 |
| Language | Every screen, message, report and help page in English and Spanish | 3.1.2 |

## Screens

| Light | Dark | High contrast, 150% text |
|---|---|---|
| ![Dashboard](screenshots/dashboard.png) | ![Dashboard, dark](screenshots/dark-mode.png) | ![Dashboard, high contrast](screenshots/high-contrast.png) |

| Ask ServeSync | Smart Match | Spanish |
|---|---|---|
| ![Ask ServeSync](screenshots/ask.png) | ![Smart Match](screenshots/smart-match.png) | ![Dashboard in Spanish](screenshots/dashboard-es.png) |
