"""
Name matcher — builds a MappingTable from a roster for the names/names_patterns tiers.

NICKNAME_TABLE: canonical uppercase name → list of common nickname/variant uppercase names.
build_name_mapping(entries, text=None) → MappingTable.

When text is provided only entries whose original string actually appears in the
document text (using word-boundary matching identical to the replacer) are
emitted.  This keeps the mapping table to exactly what was found, not every
possible variant that could theoretically match.  text=None falls back to the
full variant set (backward compatible for callers and tests that don't have text).
"""

import re
from typing import List, Optional

from backend.services.mapper import MappingEntry, MappingTable
from backend.services.roster_parser import RosterEntry


# ---------------------------------------------------------------------------
# Nickname table (canonical UPPERCASE → list of UPPERCASE nicknames)
# ---------------------------------------------------------------------------

NICKNAME_TABLE: dict = {
    # Men
    "ALEXANDER":   ["ALEX", "AL", "SANDY", "XANDER", "ALEC", "SASHA"],
    "ALFRED":      ["AL", "FRED", "ALFIE", "ALF"],
    "ANDREW":      ["ANDY", "DREW", "AND"],
    "ANTHONY":     ["TONY", "ANT", "TONI"],
    "BENJAMIN":    ["BEN", "BENNY", "BENJ", "BENJI"],
    "CHARLES":     ["CHARLIE", "CHUCK", "CHAS", "CHAD"],
    "CHRISTOPHER": ["CHRIS", "TOPHER", "KIT", "KRIS"],
    "DANIEL":      ["DAN", "DANNY", "DANI"],
    "DAVID":       ["DAVE", "DAVY", "DAV"],
    "DONALD":      ["DON", "DONNIE", "DONNY"],
    "DOUGLAS":     ["DOUG", "DOUGIE"],
    "EDWARD":      ["ED", "EDDIE", "NED", "TED", "TEDDY", "EDDY"],
    "EUGENE":      ["GENE", "GENO"],
    "FRANCIS":     ["FRANK", "FRAN", "FRANKIE"],
    "FREDERICK":   ["FRED", "FREDDIE", "RICK", "FREDDY"],
    "GEORGE":      ["GEORGIE", "GEO"],
    "GERALD":      ["GERRY", "JERRY", "GER"],
    "GREGORY":     ["GREG", "GREGG"],
    "HAROLD":      ["HARRY", "HAL"],
    "HENRY":       ["HANK", "HAL", "HARRY"],
    "JACOB":       ["JAKE", "JAC"],
    "JAMES":       ["JIM", "JIMMY", "JAMIE", "JAY"],
    "JEFFREY":     ["JEFF", "GEOFF"],
    "JOHN":        ["JACK", "JOHNNY", "JON"],
    "JONATHAN":    ["JON", "JOHNNY", "JONAH"],
    "JOSEPH":      ["JOE", "JOEY", "JO"],
    "KENNETH":     ["KEN", "KENNY"],
    "KEVIN":       ["KEV"],
    "LAWRENCE":    ["LARRY", "LARS", "LAWR"],
    "LEONARD":     ["LEN", "LENNY", "LEO"],
    "MATTHEW":     ["MATT", "MATTIE", "MAT"],
    "MICHAEL":     ["MIKE", "MICK", "MICKEY", "MICKY"],
    "NICHOLAS":    ["NICK", "NICKY", "NICOLAS"],
    "PATRICK":     ["PAT", "PADDY", "RICK"],
    "PETER":       ["PETE", "PET"],
    "PHILIP":      ["PHIL", "PHILLIP"],
    "RAYMOND":     ["RAY", "RAYMOND"],
    "RICHARD":     ["RICK", "RICH", "RICHIE", "DICK", "RICKY"],
    "ROBERT":      ["ROB", "BOB", "ROBBIE", "BOBBY", "BOBB"],
    "RONALD":      ["RON", "RONNIE", "RONNY"],
    "SAMUEL":      ["SAM", "SAMMY"],
    "STEPHEN":     ["STEVE", "STEPH", "STEVIE"],
    "STEVEN":      ["STEVE", "STEPH", "STEVIE"],
    "THOMAS":      ["TOM", "TOMMY"],
    "TIMOTHY":     ["TIM", "TIMMY"],
    "WALTER":      ["WALT", "WALLY"],
    "WILLIAM":     ["WILL", "BILL", "BILLY", "LIAM", "WILLS"],
    "ALBERT":      ["AL", "BERT", "ALBIE"],
    "CLIFFORD":    ["CLIFF", "CLIFFY"],
    "ERNEST":      ["ERNIE", "ERN"],
    "GABRIEL":     ["GABE", "GAB"],
    "NATHAN":      ["NAT", "NATE"],
    "NATHANIEL":   ["NAT", "NATE", "NATH"],
    "OLIVER":      ["OLLIE", "OLI"],
    "OSCAR":       ["OZ", "OSC"],
    "TRAVIS":      ["TRAV"],
    "TREVOR":      ["TREV"],
    "CHRISTOPHER": ["CHRIS", "KIT", "TOPHER"],
    # Women
    "ABIGAIL":     ["ABBY", "ABBIE", "GAIL", "ABI"],
    "ALEXANDRA":   ["ALEX", "ALEXA", "SANDY", "SANDRA"],
    "ALICE":       ["ALI", "ALLIE"],
    "AMANDA":      ["MANDY", "AMY", "MANDA"],
    "AMELIA":      ["AMY", "MILLIE", "MEL", "EMMY"],
    "ANDREA":      ["ANDIE", "DREA", "ANDY"],
    "BARBARA":     ["BARB", "BARBIE", "BAR"],
    "BEATRICE":    ["BEA", "BETTE", "TRIXIE"],
    "CAROLINE":    ["CARRIE", "CAROL", "CARA", "CARO"],
    "CATHERINE":   ["CAT", "CATHY", "KATE", "KATIE", "KAY"],
    "CHARLOTTE":   ["CHARLIE", "LOTTIE", "CHAR", "SHARLOTTE"],
    "CHRISTINA":   ["CHRIS", "TINA", "CHRISTIE", "KRIS"],
    "CHRISTINE":   ["CHRIS", "TINA", "CHRISSY"],
    "DEBORAH":     ["DEB", "DEBBIE", "DEBBY"],
    "DOROTHY":     ["DOT", "DOTTY", "DOLLY"],
    "ELIZABETH":   ["BETH", "BETTY", "ELIZA", "LIZ", "LISA", "ELLE", "LIBBY", "BETSY", "BESS"],
    "EMILY":       ["EM", "EMMY", "EMMI"],
    "FRANCES":     ["FRAN", "FRANKIE", "FANNY"],
    "GLORIA":      ["GLORY", "GLO"],
    "HARRIET":     ["HATTIE", "HARRY", "HATTY"],
    "HELEN":       ["NELL", "NELLIE", "HEL"],
    "JACQUELINE":  ["JACKIE", "JACQUI", "JACKY"],
    "JENNIFER":    ["JEN", "JENNY", "JENNI", "JEN"],
    "JESSICA":     ["JESS", "JESSIE", "JESSI"],
    "JUDITH":      ["JUDY", "JUDI"],
    "JULIA":       ["JULIE", "JULES"],
    "JULIET":      ["JULIE", "JULES"],
    "KATHERINE":   ["KATE", "KAT", "KATHY", "KATIE", "KAY"],
    "KATHLEEN":    ["KATHY", "KATE", "KAY"],
    "KIMBERLY":    ["KIM", "KIMMY"],
    "LAURA":       ["LAURIE", "LAU"],
    "LINDA":       ["LINDY", "LIN", "LYNDA"],
    "MARGARET":    ["MAGGIE", "MEG", "PEGGY", "MARGE", "RITA", "DAISY"],
    "MARY":        ["MOLLY", "POLLY", "MAE", "MAMIE"],
    "MELISSA":     ["MISSY", "MEL", "LISSA"],
    "NANCY":       ["NAN", "NANCE"],
    "PATRICIA":    ["PAT", "PATTY", "TRICIA", "TRISH"],
    "RACHEL":      ["RAE", "RACH"],
    "REBECCA":     ["BECKY", "BECCA", "BEX"],
    "SANDRA":      ["SANDY", "SANDI"],
    "SARAH":       ["SARA", "SALLY", "SAL"],
    "STEPHANIE":   ["STEPH", "STEVIE"],
    "SUSAN":       ["SUE", "SUZY", "SUSIE"],
    "THERESA":     ["TERRY", "TESS", "TESSA"],
    "VICTORIA":    ["VIC", "VICKY", "TORI"],
    "VIRGINIA":    ["GINNY", "GINA"],
    "CLAIRE":      ["CLARA", "CLA"],
    "DIANA":       ["DI", "DEE"],
    "ELEANOR":     ["ELLIE", "NELL", "NORA"],
    "GRACE":       ["GRACIE"],
    "ISABELLA":    ["BELLA", "IZZY", "IZZ"],
    "JOSEPHINE":   ["JO", "JOSIE", "JOE"],
    "LEAH":        ["LEA"],
    "NATALIE":     ["NAT", "NATTY"],
    "OLIVIA":      ["LIVVY", "LIV", "OLI"],
    "PENELOPE":    ["PEN", "PENNY"],
    "SOPHIA":      ["SOPHIE", "SOF"],
    "VIOLET":      ["VI", "LETTIE"],
}


# ---------------------------------------------------------------------------
# Text-presence check (same boundary logic as replacer._bounded)
# ---------------------------------------------------------------------------

def _appears_in_text(original: str, text: str) -> bool:
    """Return True if *original* appears in *text* with correct word boundaries."""
    if not text or not original:
        return False
    escaped = re.escape(original)
    pre = r'\b' if re.match(r'\w', original[0]) else ''
    suf = r'\b' if re.match(r'\w', original[-1]) else ''
    return bool(re.search(pre + escaped + suf, text))


# ---------------------------------------------------------------------------
# Variant generation
# ---------------------------------------------------------------------------

def _generate_variants(entry: RosterEntry) -> List[str]:
    """Generate all name forms for one student, including nickname variants."""
    first = (entry.first_name or "").strip()
    last = (entry.last_name or "").strip()
    preferred = (entry.preferred_name or "").strip()

    # Collect all "first names" to iterate: canonical, preferred, and nicknames
    first_names: List[str] = []
    if first:
        first_names.append(first)
    if preferred and preferred != first:
        first_names.append(preferred)
    # Add nicknames for canonical first name
    for nn in NICKNAME_TABLE.get(first.upper(), []):
        nick = nn.capitalize()
        if nick not in first_names:
            first_names.append(nick)
    # Add nicknames for preferred name
    for nn in NICKNAME_TABLE.get(preferred.upper(), []):
        nick = nn.capitalize()
        if nick not in first_names:
            first_names.append(nick)

    _TITLES = ["Professor", "Prof.", "Dr.", "Mr.", "Mrs.", "Ms.", "Miss", "Mx."]

    variants: set = set()
    for fn in first_names:
        if last:
            variants.add(f"{fn} {last}")        # Jane Smith
            variants.add(f"{last} {fn}")        # Smith Jane
            variants.add(f"{last}, {fn}")       # Smith, Jane
        if fn and last:
            initial = fn[0]
            variants.add(f"{initial}. {last}")  # J. Smith
            variants.add(f"{initial} {last}")   # J Smith

    if last:
        variants.add(last)                      # Smith (standalone last name)
        for title in _TITLES:
            variants.add(f"{title} {last}")     # Dr. Smith / Professor Smith / …

    # Add lowercase variants so case-insensitive text is caught
    lowercase_variants = {v.lower() for v in variants}
    variants.update(lowercase_variants)

    # Filter: minimum 2 chars
    return [v for v in variants if len(v.strip()) >= 2]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_name_mapping(
    roster_entries: List[RosterEntry],
    text: Optional[str] = None,
) -> MappingTable:
    """
    Build a MappingTable from a list of RosterEntry objects.

    Emits entries for four PII types (all case-insensitive via lowercase variants):
      [PERSON_N]   — fuzzy name matching (all name/nickname variants)
      [ID_N]       — exact match on student_id / id
      [EMAIL_N]    — exact match on email
      [REDACTED_N] — exact match on each semicolon-separated term in also_remove

    When *text* is provided (the combined document text), only originals that
    actually appear in the text are emitted — keeping the mapping table to
    exactly what was found rather than every theoretical variant.  Counters
    remain gap-free: if person 2 of 3 is absent from the document, the two
    present people are assigned [PERSON_1] and [PERSON_2].

    text=None: full variant set is emitted (backward compatible).

    Each counter is independent (PERSON starts at 1, ID starts at 1, etc.).
    Duplicates within each type are deduplicated across all roster entries.
    Returns an empty MappingTable for an empty roster.
    """
    if not roster_entries:
        return MappingTable(entries=[])

    filter_by_text = text is not None  # empty string → filter (yields nothing)

    all_entries: List[MappingEntry] = []

    person_counter = 0
    id_counter = 0
    email_counter = 0
    redacted_counter = 0

    seen_ids: set = set()
    seen_emails: set = set()
    seen_redacted: set = set()

    for entry in roster_entries:
        # --- Name variants → [PERSON_N] ---
        has_name = bool((entry.first_name or "").strip() or (entry.last_name or "").strip())
        if has_name:
            variants = _generate_variants(entry)

            if filter_by_text:
                variants = [v for v in variants if _appears_in_text(v, text)]

            if variants:  # only assign a placeholder if something matched
                person_counter += 1
                placeholder = f"[PERSON_{person_counter}]"
                seen_originals: set = set()
                for variant in variants:
                    v = variant.strip()
                    if len(v) < 2 or v in seen_originals:
                        continue
                    seen_originals.add(v)
                    all_entries.append(MappingEntry(
                        original=v,
                        placeholder=placeholder,
                        pii_type="PERSON",
                        source="roster",
                    ))

        # --- student_id → [ID_N] (exact, case-insensitive) ---
        sid = (entry.student_id or "").strip()
        if sid and sid not in seen_ids:
            # Check either case variant against the text
            sid_present = (not filter_by_text) or _appears_in_text(sid, text) or _appears_in_text(sid.lower(), text)
            if sid_present:
                seen_ids.add(sid)
                id_counter += 1
                ph = f"[ID_{id_counter}]"
                all_entries.append(MappingEntry(original=sid, placeholder=ph, pii_type="ID", source="roster"))
                if sid.lower() != sid:
                    all_entries.append(MappingEntry(original=sid.lower(), placeholder=ph, pii_type="ID", source="roster"))

        # --- email → [EMAIL_N] (exact, case-insensitive) ---
        em = (entry.email or "").strip()
        if em:
            em_lc = em.lower()
            if em_lc not in seen_emails:
                em_present = (not filter_by_text) or _appears_in_text(em, text) or _appears_in_text(em_lc, text)
                if em_present:
                    seen_emails.add(em_lc)
                    email_counter += 1
                    ph = f"[EMAIL_{email_counter}]"
                    all_entries.append(MappingEntry(original=em, placeholder=ph, pii_type="EMAIL", source="roster"))
                    if em_lc != em:
                        all_entries.append(MappingEntry(original=em_lc, placeholder=ph, pii_type="EMAIL", source="roster"))

        # --- also_remove → [REDACTED_N] (semicolon-separated, exact, case-insensitive) ---
        if entry.also_remove:
            for term in entry.also_remove.split(";"):
                term = term.strip()
                if len(term) < 2:
                    continue
                term_lc = term.lower()
                if term_lc in seen_redacted:
                    continue
                term_present = (not filter_by_text) or _appears_in_text(term, text) or _appears_in_text(term_lc, text)
                if term_present:
                    seen_redacted.add(term_lc)
                    redacted_counter += 1
                    ph = f"[REDACTED_{redacted_counter}]"
                    all_entries.append(MappingEntry(original=term, placeholder=ph, pii_type="REDACTED", source="roster"))
                    if term_lc != term:
                        all_entries.append(MappingEntry(original=term_lc, placeholder=ph, pii_type="REDACTED", source="roster"))

    return MappingTable(entries=all_entries)
