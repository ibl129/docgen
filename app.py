import os
import io
import json
import uuid
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_file, Response, abort
)
from dotenv import load_dotenv
from supabase import create_client, Client
from docx import Document

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.wsgi_app = __import__('whitenoise').WhiteNoise(app.wsgi_app, root='static/', prefix='static')

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "docgen-files")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def get_config() -> dict:
    """Load tenant config from Supabase config table, with env var fallbacks."""
    defaults = {
        "tenant_name": os.environ.get("TENANT_NAME", "Mijn Organisatie"),
        "primary_color": os.environ.get("PRIMARY_COLOR", "#2563EB"),
        "logo_url": "",
    }
    try:
        rows = supabase.table("config").select("key,value").execute()
        if rows.data:
            for row in rows.data:
                defaults[row["key"]] = row["value"]
    except Exception:
        pass
    return defaults


def set_config(key: str, value: str) -> None:
    supabase.table("config").upsert({"key": key, "value": value}).execute()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_code"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_code"):
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            flash("Je hebt geen toegang tot dit onderdeel.", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Word generation
# ---------------------------------------------------------------------------

def _replace_in_paragraph(para, values: dict):
    """Replace placeholders in a paragraph, even when split across multiple runs."""
    for key, val in values.items():
        placeholder = f"{{{{{key}}}}}"
        if placeholder not in para.text:
            continue
        # Fast path: placeholder fits in a single run
        for run in para.runs:
            if placeholder in run.text:
                run.text = run.text.replace(placeholder, str(val) if val is not None else "")
        if placeholder not in para.text:
            continue
        # Slow path: placeholder is split across runs — merge all run text, replace, rewrite first run
        full_text = "".join(r.text for r in para.runs)
        if placeholder not in full_text:
            continue
        new_text = full_text.replace(placeholder, str(val) if val is not None else "")
        for i, run in enumerate(para.runs):
            run.text = new_text if i == 0 else ""


SYSTEM_VARIABLES = [
    ("_datum_vandaag",      "Datum van aanmaken document (bijv. 12 mei 2026)"),
    ("_datum_iso",          "Datum in ISO-formaat (bijv. 2026-05-12)"),
    ("_jaar",               "Huidig jaar (bijv. 2026)"),
    ("_jaar-1",             "Vorig jaar (bijv. 2025)"),
    ("_jaar+1",             "Volgend jaar (bijv. 2027)"),
    ("_maand",              "Huidige maand voluit (bijv. mei)"),
    ("_tenant_naam",        "Naam van de organisatie uit de instellingen"),
    ("_ingevuld_door",      "Label van de toegangscode waarmee ingelogd is"),
    ("_dossier_naam",       "Naam van het dossier (alleen bij dossier-download)"),
    ("_dossier_omschrijving", "Omschrijving van het dossier (alleen bij dossier-download)"),
    ("_bijlagen_lijst",     "Kommalijst van alle sjabloonnamen in het dossier"),
    ("_bijlagen_aantal",    "Aantal sjablonen in het dossier"),
    ("_bijlage_volgnummer", "Volgnummer van dit sjabloon binnen het dossier (bijv. 2)"),
]

MAANDEN = ["januari","februari","maart","april","mei","juni",
           "juli","augustus","september","oktober","november","december"]

def build_system_values(cfg: dict, dossier: dict = None, templates_in_dossier: list = None, positie: int = None, user_label: str = None) -> dict:
    now = datetime.now()
    sv = {
        "_datum_vandaag": f"{now.day} {MAANDEN[now.month - 1]} {now.year}",
        "_datum_iso":     now.strftime("%Y-%m-%d"),
        "_jaar":          str(now.year),
        "_jaar-1":        str(now.year - 1),
        "_jaar+1":        str(now.year + 1),
        "_maand":         MAANDEN[now.month - 1],
        "_tenant_naam":   cfg.get("tenant_name", ""),
        "_ingevuld_door": user_label or "",
        "_dossier_naam":          (dossier or {}).get("naam", ""),
        "_dossier_omschrijving":  (dossier or {}).get("omschrijving", ""),
        "_bijlagen_lijst":    ", ".join(t.get("name", "") for t in (templates_in_dossier or [])),
        "_bijlagen_aantal":   str(len(templates_in_dossier)) if templates_in_dossier is not None else "",
        "_bijlage_volgnummer": str(positie) if positie is not None else "",
    }
    return sv


DATE_FORMATS = {
    "DD-MM-YYYY":   "%d-%m-%Y",
    "DD-MM-YY":     "%d-%m-%y",
    "D MMM YYYY":   None,   # speciaal: Nederlandse afkorting
    "D MMMM YYYY":  None,   # speciaal: Nederlandse voluit
    "YYYY-MM-DD":   "%Y-%m-%d",
}

MAANDEN_KORT = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]

def _format_date(iso_str: str, fmt_key: str) -> str:
    from datetime import datetime as dt
    try:
        d = dt.strptime(iso_str, "%Y-%m-%d")
    except ValueError:
        return iso_str
    if fmt_key == "D MMM YYYY":
        return f"{d.day} {MAANDEN_KORT[d.month - 1]} {d.year}"
    if fmt_key == "D MMMM YYYY":
        return f"{d.day} {MAANDEN[d.month - 1]} {d.year}"
    strfmt = DATE_FORMATS.get(fmt_key, "%d-%m-%Y")
    return d.strftime(strfmt)


def format_field_values(fields: list, values: dict) -> dict:
    """Zet datum-velden om naar gewenst formaat en laat overige waarden intact."""
    result = dict(values)
    for field in fields:
        key = field.get("name")
        if field.get("type") == "date" and key in result and result[key]:
            fmt_key = field.get("date_format", "DD-MM-YYYY")
            result[key] = _format_date(result[key], fmt_key)
    return result


import re as _re
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from copy import deepcopy
import lxml.etree as _etree

_IF_RE    = _re.compile(r'\{\{#if\s+(\w+)\}\}')
_IFNOT_RE = _re.compile(r'\{\{#ifnot\s+(\w+)\}\}')
_ENDIF_RE = _re.compile(r'\{\{/if(?:not)?\}\}')


def _para_full_text(para) -> str:
    return "".join(r.text for r in para.runs)


def _para_set_text(para, text: str):
    """Overschrijf alle runs: eerste run krijgt volledige tekst, rest leeg.
    Verwijdert ook w:br elementen uit alle runs én als directe kind van w:p."""
    # Verwijder w:br direct onder w:p
    for br in para._element.findall(qn('w:br')):
        para._element.remove(br)
    # Verwijder w:br binnen w:r elementen
    for r_elem in para._element.findall(qn('w:r')):
        for br in r_elem.findall(qn('w:br')):
            r_elem.remove(br)
    if para.runs:
        para.runs[0].text = text
        for r in para.runs[1:]:
            r.text = ""
    else:
        para.add_run(text)


def _remove_para_spacing(p_elem):
    """Zet w:spacing after/before op 0 in de pPr van een alinea-element."""
    pPr = p_elem.find(qn('w:pPr'))
    if pPr is None:
        pPr = OxmlElement('w:pPr')
        p_elem.insert(0, pPr)
    # Verwijder bestaand spacing-element en vervang met schone versie
    for old in pPr.findall(qn('w:spacing')):
        pPr.remove(old)
    spacing = OxmlElement('w:spacing')
    spacing.set(qn('w:after'), '0')
    spacing.set(qn('w:before'), '0')
    spacing.set(qn('w:line'), '240')
    spacing.set(qn('w:lineRule'), 'auto')
    pPr.append(spacing)
    # contextualSpacing voorkomt extra ruimte tussen alinea's van dezelfde stijl (o.a. lijsten)
    for old in pPr.findall(qn('w:contextualSpacing')):
        pPr.remove(old)
    ctx = OxmlElement('w:contextualSpacing')
    ctx.set(qn('w:val'), '0')
    pPr.append(ctx)


def _insert_paragraph_after(ref_para, text: str, source_para, remove_spacing: bool = False):
    """Voeg een nieuwe alinea in direct na ref_para, met alinea-opmaak van source_para."""
    from docx.text.paragraph import Paragraph as DocxParagraph

    # Kopieer de alinea-structuur (inclusief pPr/opmaak), maar zonder runs en w:br
    new_p = deepcopy(source_para._element)
    for r in new_p.findall(qn('w:r')):
        new_p.remove(r)
    for br in new_p.findall(qn('w:br')):
        new_p.remove(br)

    if remove_spacing:
        _remove_para_spacing(new_p)

    # Bouw een nieuwe run met de tekst
    new_r = OxmlElement('w:r')
    # Kopieer run-opmaak van eerste run als die er is
    if source_para.runs:
        rpr = source_para.runs[0]._element.find(qn('w:rPr'))
        if rpr is not None:
            new_r.append(deepcopy(rpr))
    new_t = OxmlElement('w:t')
    new_t.text = text
    new_t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    new_r.append(new_t)
    new_p.append(new_r)

    ref_para._element.addnext(new_p)
    return DocxParagraph(new_p, source_para._element.getparent())


def _process_conditionals(paragraphs_parent, values: dict):
    """
    Verwerk {{#if veld}}, {{#ifnot veld}}, {{/if}} / {{/ifnot}} blokken.
    Alinea's die in een falende conditie vallen worden verwijderd.
    Werkt op de directe kinderen van een body/cell-element.
    """
    from docx.text.paragraph import Paragraph as DocxPara

    # Verzamel alle paragrafen als lijst van (element, tekst)
    body = paragraphs_parent
    paras = [child for child in body if child.tag == qn('w:p')]

    to_delete = set()
    i = 0
    while i < len(paras):
        p = paras[i]
        text = "".join(t.text or "" for t in p.iter(qn('w:t')))

        m_if    = _IF_RE.search(text)
        m_ifnot = _IFNOT_RE.search(text)

        if m_if or m_ifnot:
            field   = (m_if or m_ifnot).group(1)
            is_if   = bool(m_if)
            filled  = bool(values.get(field, "").strip())
            keep    = filled if is_if else not filled

            # Markeer de openingsregel zelf voor verwijdering
            to_delete.add(id(p))
            i += 1

            # Zoek de bijbehorende {{/if}} of {{/ifnot}}
            depth = 1
            while i < len(paras) and depth > 0:
                inner = paras[i]
                inner_text = "".join(t.text or "" for t in inner.iter(qn('w:t')))
                if _IF_RE.search(inner_text) or _IFNOT_RE.search(inner_text):
                    depth += 1
                if _ENDIF_RE.search(inner_text):
                    depth -= 1
                    if depth == 0:
                        to_delete.add(id(inner))  # sluitingstag verwijderen
                        i += 1
                        break
                if not keep:
                    to_delete.add(id(inner))
                i += 1
        else:
            i += 1

    for p in paras:
        if id(p) in to_delete:
            p.getparent().remove(p)


def _process_textarea(para, values: dict):
    """
    Als een alinea een textarea-placeholder bevat met meerdere regels (\n),
    vervang de alinea door meerdere alinea's (één per regel).
    Anders: gewone placeholder-vervanging.
    """
    # Herstel de volledige tekst inclusief gesplitste runs
    full_text = "".join(r.text or "" for r in para.runs)

    for key, val in values.items():
        placeholder = f"{{{{{key}}}}}"
        if placeholder not in full_text:
            continue
        val_str = str(val) if val is not None else ""
        # Normaliseer Windows CRLF naar LF
        val_str = val_str.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" not in val_str:
            continue
        # Multiline: trim afsluitende lege regels, splits op newlines
        lines = val_str.rstrip("\n").split("\n")
        # Verwijder spacing van de originele alinea (w:br wordt door _para_set_text verwijderd)
        _remove_para_spacing(para._element)
        first_line_text = full_text.replace(placeholder, lines[0])
        _para_set_text(para, first_line_text)
        # Volgende regels als nieuwe alinea's, allemaal zonder spacing
        prev = para
        for line in lines[1:]:
            line_text = full_text.replace(placeholder, line)
            prev = _insert_paragraph_after(prev, line_text, para, remove_spacing=True)
        return  # klaar, sla gewone vervanging over

    # Geen multiline — gewone vervanging
    _replace_in_paragraph(para, values)


def fill_template(docx_bytes: bytes, values: dict) -> bytes:
    doc = Document(io.BytesIO(docx_bytes))

    # Normaliseer Windows CRLF in alle waarden (browsers sturen \r\n vanuit textarea)
    values = {k: v.replace("\r\n", "\n").replace("\r", "\n") if isinstance(v, str) else v
              for k, v in values.items()}

    # Stap 1: conditionele blokken verwerken (verwijdert alinea's)
    _process_conditionals(doc.element.body, values)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                _process_conditionals(cell._tc, values)

    # Stap 2: placeholders vervangen (inclusief multiline textarea)
    for para in doc.paragraphs:
        _process_textarea(para, values)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _process_textarea(para, values)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    cfg = get_config()
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        if not code:
            flash("Voer een toegangscode in.", "error")
            return render_template("login.html", cfg=cfg)

        try:
            row = supabase.table("access_codes").select("*").eq("code", code).single().execute()
        except Exception as e:
            app.logger.error(f"Supabase login fout: {e}")
            row = None

        app.logger.info(f"Login poging code={code!r} row={row}")
        if row and row.data:
            session["user_code"] = row.data["code"]
            session["user_label"] = row.data.get("label", code)
            session["is_admin"] = bool(row.data.get("is_admin", False))
            return redirect(url_for("index"))
        else:
            flash("Ongeldige toegangscode.", "error")

    return render_template("login.html", cfg=cfg)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Internal routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    cfg = get_config()
    try:
        templates = supabase.table("templates").select("id,name,description,created_at").order("created_at", desc=True).execute()
        tmpl_list = templates.data or []
    except Exception as e:
        flash(f"Fout bij ophalen sjablonen: {e}", "error")
        tmpl_list = []
    return render_template("index.html", cfg=cfg, templates=tmpl_list)


@app.route("/template/<template_id>")
@login_required
def template_detail(template_id):
    cfg = get_config()
    try:
        tmpl = supabase.table("templates").select("*").eq("id", template_id).single().execute()
    except Exception:
        abort(404)

    if not tmpl.data:
        abort(404)

    template = tmpl.data
    fields = template.get("fields") or []
    if isinstance(fields, str):
        fields = json.loads(fields)

    try:
        tokens_res = supabase.table("tokens").select("*").eq("template_id", template_id).order("created_at", desc=True).execute()
        tokens = tokens_res.data or []
    except Exception:
        tokens = []

    return render_template(
        "template_detail.html",
        cfg=cfg,
        template=template,
        fields=fields,
        tokens=tokens,
    )


@app.route("/template/<template_id>/download", methods=["POST"])
@login_required
def template_download(template_id):
    try:
        tmpl = supabase.table("templates").select("*").eq("id", template_id).single().execute()
    except Exception:
        abort(404)

    if not tmpl.data:
        abort(404)

    template = tmpl.data
    fields = template.get("fields") or []
    if isinstance(fields, str):
        fields = json.loads(fields)

    values = {}
    for field in fields:
        key = field["name"]
        values[key] = request.form.get(key, "")

    values = format_field_values(fields, values)
    cfg = get_config()
    system_vals = build_system_values(cfg, user_label=session.get("user_label", ""))
    values = {**system_vals, **values}

    try:
        docx_bytes = supabase.storage.from_(SUPABASE_BUCKET).download(template["docx_path"])
    except Exception as e:
        flash(f"Fout bij ophalen sjabloonbestand: {e}", "error")
        return redirect(url_for("template_detail", template_id=template_id))

    try:
        result = fill_template(docx_bytes, values)
    except Exception as e:
        flash(f"Fout bij genereren document: {e}", "error")
        return redirect(url_for("template_detail", template_id=template_id))

    filename = f"{template['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    return send_file(
        io.BytesIO(result),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/template/<template_id>/tokens/create", methods=["POST"])
@login_required
def token_create(template_id):
    description = request.form.get("description", "").strip() or "Extern formulier"
    try:
        supabase.table("tokens").insert({
            "template_id": template_id,
            "description": description,
            "status": "pending",
        }).execute()
        flash("Token aangemaakt.", "success")
    except Exception as e:
        flash(f"Fout bij aanmaken token: {e}", "error")
    return redirect(url_for("template_detail", template_id=template_id))


@app.route("/token/<token_id>/unseal", methods=["POST"])
@login_required
def token_unseal(token_id):
    try:
        # Fetch token to get template_id for redirect
        tok = supabase.table("tokens").select("template_id").eq("id", token_id).single().execute()
        supabase.table("tokens").update({"status": "pending"}).eq("id", token_id).execute()
        flash("Token heropend — formulier kan opnieuw worden ingevuld.", "success")
        if tok.data:
            return redirect(url_for("template_detail", template_id=tok.data["template_id"]))
    except Exception as e:
        flash(f"Fout bij heropenen token: {e}", "error")
    return redirect(url_for("index"))


@app.route("/token/<token_id>/download")
@login_required
def token_download(token_id):
    try:
        tok = supabase.table("tokens").select("*").eq("id", token_id).single().execute()
    except Exception:
        abort(404)

    if not tok.data:
        abort(404)

    token = tok.data
    if token["status"] != "sealed":
        flash("Dit token heeft nog geen ingediende invulling.", "error")
        return redirect(url_for("template_detail", template_id=token["template_id"]))

    try:
        sub = supabase.table("submissions").select("*").eq("token_id", token_id).order("submitted_at", desc=True).limit(1).single().execute()
    except Exception:
        flash("Geen inzending gevonden voor dit token.", "error")
        return redirect(url_for("template_detail", template_id=token["template_id"]))

    if not sub.data:
        flash("Geen inzending gevonden voor dit token.", "error")
        return redirect(url_for("template_detail", template_id=token["template_id"]))

    values = sub.data.get("values") or {}
    if isinstance(values, str):
        values = json.loads(values)

    try:
        tmpl = supabase.table("templates").select("*").eq("id", token["template_id"]).single().execute()
    except Exception:
        abort(404)

    template = tmpl.data
    t_fields = template.get("fields") or []
    if isinstance(t_fields, str):
        t_fields = json.loads(t_fields)
    values = format_field_values(t_fields, values)
    cfg = get_config()
    system_vals = build_system_values(cfg, user_label=session.get("user_label", ""))
    values = {**system_vals, **values}

    try:
        docx_bytes = supabase.storage.from_(SUPABASE_BUCKET).download(template["docx_path"])
    except Exception as e:
        flash(f"Fout bij ophalen sjabloonbestand: {e}", "error")
        return redirect(url_for("template_detail", template_id=token["template_id"]))

    result = fill_template(docx_bytes, values)
    desc = token.get("description", "document").replace(" ", "_")
    filename = f"{desc}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    return send_file(
        io.BytesIO(result),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


# ---------------------------------------------------------------------------
# External routes (no login)
# ---------------------------------------------------------------------------

@app.route("/fill/<token_id>", methods=["GET", "POST"])
def fill_external(token_id):
    cfg = get_config()
    try:
        tok = supabase.table("tokens").select("*").eq("id", token_id).single().execute()
    except Exception:
        abort(404)

    if not tok.data:
        abort(404)

    token = tok.data

    if token["status"] == "sealed":
        return render_template("fill_thanks.html", cfg=cfg, already_sealed=True)

    try:
        tmpl = supabase.table("templates").select("*").eq("id", token["template_id"]).single().execute()
    except Exception:
        abort(404)

    if not tmpl.data:
        abort(404)

    template = tmpl.data
    fields = template.get("fields") or []
    if isinstance(fields, str):
        fields = json.loads(fields)

    if request.method == "POST":
        values = {}
        errors = []
        for field in fields:
            key = field["name"]
            val = request.form.get(key, "").strip()
            if field.get("required") and not val:
                errors.append(f'"{field.get("label", key)}" is verplicht.')
            values[key] = val

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "fill_external.html",
                cfg=cfg,
                template=template,
                fields=fields,
                token=token,
                prefill=values,
            )

        try:
            supabase.table("submissions").insert({
                "token_id": token_id,
                "values": values,
            }).execute()
            supabase.table("tokens").update({"status": "sealed"}).eq("id", token_id).execute()
        except Exception as e:
            flash(f"Fout bij opslaan: {e}", "error")
            return render_template(
                "fill_external.html",
                cfg=cfg,
                template=template,
                fields=fields,
                token=token,
                prefill=values,
            )

        return redirect(url_for("fill_thanks", token_id=token_id))

    return render_template(
        "fill_external.html",
        cfg=cfg,
        template=template,
        fields=fields,
        token=token,
        prefill={},
    )


@app.route("/fill/<token_id>/thanks")
def fill_thanks(token_id):
    cfg = get_config()
    try:
        tok = supabase.table("tokens").select("status").eq("id", token_id).single().execute()
        already_sealed = tok.data and tok.data.get("status") == "sealed"
    except Exception:
        already_sealed = True
    return render_template("fill_thanks.html", cfg=cfg, already_sealed=already_sealed)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin")
@admin_required
def admin():
    cfg = get_config()
    try:
        templates_res = supabase.table("templates").select("id,name,created_at").order("created_at", desc=True).execute()
        templates = templates_res.data or []
    except Exception:
        templates = []

    try:
        codes_res = supabase.table("access_codes").select("*").order("created_at", desc=True).execute()
        codes = codes_res.data or []
    except Exception:
        codes = []

    try:
        tokens_res = supabase.table("tokens").select("id,status").execute()
        token_stats = {
            "total": len(tokens_res.data or []),
            "sealed": sum(1 for t in (tokens_res.data or []) if t["status"] == "sealed"),
            "pending": sum(1 for t in (tokens_res.data or []) if t["status"] == "pending"),
        }
    except Exception:
        token_stats = {"total": 0, "sealed": 0, "pending": 0}

    return render_template(
        "admin.html",
        cfg=cfg,
        templates=templates,
        codes=codes,
        token_stats=token_stats,
        system_variables=SYSTEM_VARIABLES,
    )


@app.route("/admin/template/scan", methods=["POST"])
@admin_required
def admin_template_scan():
    """Scan een geüpload .docx bestand en geef gevonden placeholders terug als JSON."""
    docx_file = request.files.get("docx_file")
    if not docx_file or not docx_file.filename.lower().endswith(".docx"):
        return {"error": "Geen geldig .docx bestand."}, 400

    try:
        doc = Document(io.BytesIO(docx_file.read()))
    except Exception as e:
        return {"error": f"Kon bestand niet lezen: {e}"}, 400

    import re
    found = set()
    system_keys = {key for key, _ in SYSTEM_VARIABLES}

    def scan_text(text):
        for match in re.findall(r"\{\{([^}]+)\}\}", text):
            key = match.strip()
            # Sla systeemvariabelen en conditionele tags over
            if not key:
                continue
            if key in system_keys:
                continue
            if key.startswith('#if ') or key.startswith('#ifnot ') or key.startswith('/if'):
                continue
            found.add(key)

    for para in doc.paragraphs:
        scan_text(para.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    scan_text(para.text)

    return {"placeholders": sorted(found)}


@app.route("/admin/template/new", methods=["GET", "POST"])
@admin_required
def admin_template_new():
    cfg = get_config()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        fields_json = request.form.get("fields_json", "[]").strip()
        docx_file = request.files.get("docx_file")

        if not name:
            flash("Naam is verplicht.", "error")
            return render_template("admin_template_edit.html", cfg=cfg, template=None, mode="new")

        if not docx_file or not docx_file.filename:
            flash("Upload een .docx sjabloonbestand.", "error")
            return render_template("admin_template_edit.html", cfg=cfg, template=None, mode="new")

        if not docx_file.filename.lower().endswith(".docx"):
            flash("Alleen .docx bestanden zijn toegestaan.", "error")
            return render_template("admin_template_edit.html", cfg=cfg, template=None, mode="new")

        try:
            fields = json.loads(fields_json)
        except json.JSONDecodeError:
            fields = []

        file_bytes = docx_file.read()
        storage_path = f"templates/{uuid.uuid4()}.docx"

        try:
            supabase.storage.from_(SUPABASE_BUCKET).upload(
                storage_path,
                file_bytes,
                file_options={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            )
        except Exception as e:
            flash(f"Fout bij uploaden bestand: {e}", "error")
            return render_template("admin_template_edit.html", cfg=cfg, template=None, mode="new")

        try:
            supabase.table("templates").insert({
                "name": name,
                "description": description,
                "docx_path": storage_path,
                "fields": fields,
            }).execute()
            flash("Sjabloon aangemaakt.", "success")
            return redirect(url_for("admin"))
        except Exception as e:
            flash(f"Fout bij opslaan sjabloon: {e}", "error")

    return render_template("admin_template_edit.html", cfg=cfg, template=None, mode="new")


@app.route("/admin/template/<template_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_template_edit(template_id):
    cfg = get_config()
    try:
        tmpl = supabase.table("templates").select("*").eq("id", template_id).single().execute()
    except Exception:
        abort(404)

    if not tmpl.data:
        abort(404)

    template = tmpl.data
    fields = template.get("fields") or []
    if isinstance(fields, str):
        fields = json.loads(fields)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        fields_json = request.form.get("fields_json", "[]").strip()
        docx_file = request.files.get("docx_file")

        if not name:
            flash("Naam is verplicht.", "error")
            return render_template("admin_template_edit.html", cfg=cfg, template=template, fields=fields, mode="edit")

        try:
            new_fields = json.loads(fields_json)
        except json.JSONDecodeError:
            new_fields = fields

        update_data = {
            "name": name,
            "description": description,
            "fields": new_fields,
            "updated_at": datetime.utcnow().isoformat(),
        }

        if docx_file and docx_file.filename and docx_file.filename.lower().endswith(".docx"):
            file_bytes = docx_file.read()
            storage_path = f"templates/{uuid.uuid4()}.docx"
            try:
                supabase.storage.from_(SUPABASE_BUCKET).upload(
                    storage_path,
                    file_bytes,
                    file_options={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
                )
                # Delete old file
                try:
                    supabase.storage.from_(SUPABASE_BUCKET).remove([template["docx_path"]])
                except Exception:
                    pass
                update_data["docx_path"] = storage_path
            except Exception as e:
                flash(f"Fout bij uploaden nieuw bestand: {e}", "error")
                return render_template("admin_template_edit.html", cfg=cfg, template=template, fields=fields, mode="edit")

        try:
            supabase.table("templates").update(update_data).eq("id", template_id).execute()
            flash("Sjabloon bijgewerkt.", "success")
            return redirect(url_for("admin"))
        except Exception as e:
            flash(f"Fout bij opslaan: {e}", "error")

    return render_template("admin_template_edit.html", cfg=cfg, template=template, fields=fields, mode="edit")


@app.route("/admin/template/<template_id>/delete", methods=["POST"])
@admin_required
def admin_template_delete(template_id):
    try:
        tmpl = supabase.table("templates").select("docx_path").eq("id", template_id).single().execute()
        if tmpl.data:
            try:
                supabase.storage.from_(SUPABASE_BUCKET).remove([tmpl.data["docx_path"]])
            except Exception:
                pass
        supabase.table("templates").delete().eq("id", template_id).execute()
        flash("Sjabloon verwijderd.", "success")
    except Exception as e:
        flash(f"Fout bij verwijderen: {e}", "error")
    return redirect(url_for("admin"))


@app.route("/admin/config", methods=["GET", "POST"])
@admin_required
def admin_config():
    cfg = get_config()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "save_config":
            tenant_name = request.form.get("tenant_name", "").strip()
            primary_color = request.form.get("primary_color", "").strip()
            logo_url = request.form.get("logo_url", "").strip()

            if tenant_name:
                set_config("tenant_name", tenant_name)
            if primary_color:
                set_config("primary_color", primary_color)
            set_config("logo_url", logo_url)
            flash("Configuratie opgeslagen.", "success")
            return redirect(url_for("admin_config"))

        if action == "add_code":
            code = request.form.get("new_code", "").strip()
            label = request.form.get("new_label", "").strip()
            is_admin = request.form.get("new_is_admin") == "1"

            if not code:
                flash("Toegangscode is verplicht.", "error")
            else:
                try:
                    supabase.table("access_codes").insert({
                        "code": code,
                        "label": label or code,
                        "is_admin": is_admin,
                    }).execute()
                    flash("Toegangscode aangemaakt.", "success")
                except Exception as e:
                    flash(f"Fout: {e}", "error")
            return redirect(url_for("admin_config"))

        if action == "delete_code":
            code_id = request.form.get("code_id")
            try:
                supabase.table("access_codes").delete().eq("id", code_id).execute()
                flash("Toegangscode verwijderd.", "success")
            except Exception as e:
                flash(f"Fout: {e}", "error")
            return redirect(url_for("admin_config"))

    try:
        codes_res = supabase.table("access_codes").select("*").order("created_at", desc=True).execute()
        codes = codes_res.data or []
    except Exception:
        codes = []

    return render_template("admin_config.html", cfg=cfg, codes=codes)


@app.route("/admin/submissions")
@admin_required
def admin_submissions():
    cfg = get_config()
    try:
        subs_res = (
            supabase.table("submissions")
            .select("id,submitted_at,values,token_id")
            .order("submitted_at", desc=True)
            .execute()
        )
        submissions = subs_res.data or []
    except Exception as e:
        flash(f"Fout bij ophalen inzendingen: {e}", "error")
        submissions = []

    # Enrich with token + template info
    token_cache = {}
    template_cache = {}
    enriched = []
    for sub in submissions:
        tid = sub.get("token_id")
        if tid not in token_cache:
            try:
                tok = supabase.table("tokens").select("description,template_id,status").eq("id", tid).single().execute()
                token_cache[tid] = tok.data or {}
            except Exception:
                token_cache[tid] = {}

        token = token_cache.get(tid, {})
        tmpl_id = token.get("template_id")

        if tmpl_id and tmpl_id not in template_cache:
            try:
                tmpl = supabase.table("templates").select("name").eq("id", tmpl_id).single().execute()
                template_cache[tmpl_id] = tmpl.data or {}
            except Exception:
                template_cache[tmpl_id] = {}

        tmpl_data = template_cache.get(tmpl_id, {}) if tmpl_id else {}
        values = sub.get("values") or {}
        if isinstance(values, str):
            values = json.loads(values)

        enriched.append({
            **sub,
            "token_description": token.get("description", "—"),
            "template_name": tmpl_data.get("name", "—"),
            "token_status": token.get("status", "—"),
            "values": values,
        })

    return render_template("admin_submissions.html", cfg=cfg, submissions=enriched)


# ---------------------------------------------------------------------------
# Dossier routes (ingelogd vereist)
# ---------------------------------------------------------------------------

@app.route("/dossiers")
@login_required
def dossiers_overzicht():
    cfg = get_config()
    try:
        dos_res = supabase.table("dossiers").select("*").order("created_at", desc=True).execute()
        dossier_list = dos_res.data or []
    except Exception as e:
        flash(f"Fout bij ophalen dossiers: {e}", "error")
        dossier_list = []

    # Enrich with invulling count
    for dos in dossier_list:
        try:
            cnt_res = supabase.table("invullingen").select("id").eq("dossier_id", dos["id"]).execute()
            dos["invulling_count"] = len(cnt_res.data or [])
        except Exception:
            dos["invulling_count"] = 0

    return render_template("dossiers.html", cfg=cfg, dossiers=dossier_list)


@app.route("/dossier/nieuw", methods=["GET", "POST"])
@login_required
def dossier_nieuw():
    cfg = get_config()
    try:
        tmpl_res = supabase.table("templates").select("id,name,description").order("name").execute()
        templates = tmpl_res.data or []
    except Exception:
        templates = []

    if request.method == "POST":
        naam = request.form.get("naam", "").strip()
        omschrijving = request.form.get("omschrijving", "").strip()
        template_ids = request.form.getlist("template_ids")

        if not naam:
            flash("Naam is verplicht.", "error")
            return render_template("dossier_nieuw.html", cfg=cfg, templates=templates)

        if not template_ids:
            flash("Selecteer minimaal één sjabloon.", "error")
            return render_template("dossier_nieuw.html", cfg=cfg, templates=templates)

        try:
            dos_res = supabase.table("dossiers").insert({
                "naam": naam,
                "omschrijving": omschrijving or None,
            }).execute()
            dossier_id = dos_res.data[0]["id"]
        except Exception as e:
            flash(f"Fout bij aanmaken dossier: {e}", "error")
            return render_template("dossier_nieuw.html", cfg=cfg, templates=templates)

        for tid in template_ids:
            try:
                supabase.table("invullingen").insert({
                    "dossier_id": dossier_id,
                    "template_id": tid,
                    "waarden": {},
                    "extern_toegang": "verborgen",
                }).execute()
            except Exception as e:
                flash(f"Fout bij aanmaken invulling: {e}", "error")

        flash("Dossier aangemaakt.", "success")
        return redirect(url_for("dossier_detail", dossier_id=dossier_id))

    return render_template("dossier_nieuw.html", cfg=cfg, templates=templates)


@app.route("/dossier/<dossier_id>")
@login_required
def dossier_detail(dossier_id):
    cfg = get_config()
    try:
        dos_res = supabase.table("dossiers").select("*").eq("id", dossier_id).single().execute()
    except Exception:
        abort(404)

    if not dos_res.data:
        abort(404)

    dossier = dos_res.data

    try:
        inv_res = supabase.table("invullingen").select("*").eq("dossier_id", dossier_id).execute()
        invullingen_raw = inv_res.data or []
    except Exception:
        invullingen_raw = []

    # Enrich invullingen with template field definitions
    invullingen = []
    for inv in invullingen_raw:
        try:
            tmpl_res = supabase.table("templates").select("*").eq("id", inv["template_id"]).single().execute()
            tmpl = tmpl_res.data or {}
        except Exception:
            tmpl = {}
        fields = tmpl.get("fields") or []
        if isinstance(fields, str):
            fields = json.loads(fields)
        waarden = inv.get("waarden") or {}
        if isinstance(waarden, str):
            waarden = json.loads(waarden)
        invullingen.append({
            **inv,
            "template": tmpl,
            "fields": fields,
            "waarden": waarden,
            "is_filled": any(str(v).strip() for v in waarden.values()),
        })

    try:
        tok_res = supabase.table("dossier_tokens").select("*").eq("dossier_id", dossier_id).order("created_at", desc=True).execute()
        tokens = tok_res.data or []
    except Exception:
        tokens = []

    return render_template(
        "dossier_detail.html",
        cfg=cfg,
        dossier=dossier,
        invullingen=invullingen,
        tokens=tokens,
    )


@app.route("/dossier/<dossier_id>/invulling/<inv_id>", methods=["POST"])
@login_required
def dossier_invulling_opslaan(dossier_id, inv_id):
    try:
        inv_res = supabase.table("invullingen").select("*").eq("id", inv_id).eq("dossier_id", dossier_id).single().execute()
    except Exception:
        abort(404)

    if not inv_res.data:
        abort(404)

    inv = inv_res.data
    try:
        tmpl_res = supabase.table("templates").select("fields").eq("id", inv["template_id"]).single().execute()
    except Exception:
        abort(404)

    fields = tmpl_res.data.get("fields") or []
    if isinstance(fields, str):
        fields = json.loads(fields)

    waarden = {}
    for field in fields:
        key = field["name"]
        waarden[key] = request.form.get(key, "")

    try:
        supabase.table("invullingen").update({
            "waarden": waarden,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", inv_id).execute()
        flash("Invulling opgeslagen.", "success")
    except Exception as e:
        flash(f"Fout bij opslaan: {e}", "error")

    return redirect(url_for("dossier_detail", dossier_id=dossier_id))


@app.route("/dossier/<dossier_id>/invulling/<inv_id>/download")
@login_required
def dossier_invulling_download(dossier_id, inv_id):
    try:
        inv_res = supabase.table("invullingen").select("*").eq("id", inv_id).eq("dossier_id", dossier_id).single().execute()
    except Exception:
        abort(404)

    if not inv_res.data:
        abort(404)

    inv = inv_res.data
    waarden = inv.get("waarden") or {}
    if isinstance(waarden, str):
        waarden = json.loads(waarden)

    try:
        tmpl_res = supabase.table("templates").select("*").eq("id", inv["template_id"]).single().execute()
    except Exception:
        abort(404)

    template = tmpl_res.data
    fields = template.get("fields") or []
    if isinstance(fields, str):
        fields = json.loads(fields)
    waarden = format_field_values(fields, waarden)

    # Haal dossier + alle invullingen op voor systeemvariabelen
    try:
        dos_res = supabase.table("dossiers").select("*").eq("id", dossier_id).single().execute()
        alle_inv = supabase.table("invullingen").select("template_id").eq("dossier_id", dossier_id).execute()
        template_ids = [i["template_id"] for i in (alle_inv.data or [])]
        alle_tmpl = supabase.table("templates").select("id,name").in_("id", template_ids).execute()
        tmpl_map = {t["id"]: t for t in (alle_tmpl.data or [])}
        templates_in_dossier = [tmpl_map[tid] for tid in template_ids if tid in tmpl_map]
        positie = next((i + 1 for i, tid in enumerate(template_ids) if tid == inv["template_id"]), None)
        dossier = dos_res.data or {}
    except Exception:
        templates_in_dossier = [template]
        positie = 1
        dossier = {}

    cfg = get_config()
    system_vals = build_system_values(
        cfg,
        dossier=dossier,
        templates_in_dossier=templates_in_dossier,
        positie=positie,
        user_label=session.get("user_label", ""),
    )
    waarden = {**system_vals, **waarden}

    try:
        docx_bytes = supabase.storage.from_(SUPABASE_BUCKET).download(template["docx_path"])
    except Exception as e:
        flash(f"Fout bij ophalen sjabloonbestand: {e}", "error")
        return redirect(url_for("dossier_detail", dossier_id=dossier_id))

    try:
        result = fill_template(docx_bytes, waarden)
    except Exception as e:
        flash(f"Fout bij genereren document: {e}", "error")
        return redirect(url_for("dossier_detail", dossier_id=dossier_id))

    filename = f"{template['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    return send_file(
        io.BytesIO(result),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/dossier/<dossier_id>/invulling/<inv_id>/toegang", methods=["POST"])
@login_required
def dossier_invulling_toegang(dossier_id, inv_id):
    extern_toegang = request.form.get("extern_toegang", "verborgen")
    if extern_toegang not in ("verborgen", "leesbaar", "invulbaar"):
        extern_toegang = "verborgen"

    try:
        supabase.table("invullingen").update({
            "extern_toegang": extern_toegang,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", inv_id).eq("dossier_id", dossier_id).execute()
        flash("Toegang bijgewerkt.", "success")
    except Exception as e:
        flash(f"Fout bij opslaan toegang: {e}", "error")

    return redirect(url_for("dossier_detail", dossier_id=dossier_id))


@app.route("/dossier/<dossier_id>/status", methods=["POST"])
@login_required
def dossier_status(dossier_id):
    status = request.form.get("status", "concept")
    if status not in ("concept", "afgerond"):
        status = "concept"

    try:
        supabase.table("dossiers").update({
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", dossier_id).execute()
        flash("Dossier status bijgewerkt.", "success")
    except Exception as e:
        flash(f"Fout bij bijwerken status: {e}", "error")

    return redirect(url_for("dossier_detail", dossier_id=dossier_id))


@app.route("/dossier/<dossier_id>/token/aanmaken", methods=["POST"])
@login_required
def dossier_token_aanmaken(dossier_id):
    omschrijving = request.form.get("omschrijving", "").strip() or "Extern dossier"
    try:
        supabase.table("dossier_tokens").insert({
            "dossier_id": dossier_id,
            "omschrijving": omschrijving,
            "status": "actief",
        }).execute()
        flash("Deellink aangemaakt.", "success")
    except Exception as e:
        flash(f"Fout bij aanmaken deellink: {e}", "error")

    return redirect(url_for("dossier_detail", dossier_id=dossier_id))


@app.route("/dossier_token/<token_id>/intrekken", methods=["POST"])
@login_required
def dossier_token_intrekken(token_id):
    try:
        tok = supabase.table("dossier_tokens").select("dossier_id").eq("id", token_id).single().execute()
        supabase.table("dossier_tokens").update({"status": "ingetrokken"}).eq("id", token_id).execute()
        flash("Deellink ingetrokken.", "success")
        if tok.data:
            return redirect(url_for("dossier_detail", dossier_id=tok.data["dossier_id"]))
    except Exception as e:
        flash(f"Fout bij intrekken: {e}", "error")
    return redirect(url_for("dossiers_overzicht"))


# ---------------------------------------------------------------------------
# Extern dossier routes (geen login)
# ---------------------------------------------------------------------------

@app.route("/dossier/extern/<token_id>", methods=["GET", "POST"])
def dossier_extern(token_id):
    cfg = get_config()
    try:
        tok_res = supabase.table("dossier_tokens").select("*").eq("id", token_id).single().execute()
    except Exception:
        abort(404)

    if not tok_res.data:
        abort(404)

    token = tok_res.data
    if token["status"] != "actief":
        abort(404)

    dossier_id = token["dossier_id"]
    try:
        dos_res = supabase.table("dossiers").select("*").eq("id", dossier_id).single().execute()
    except Exception:
        abort(404)

    if not dos_res.data:
        abort(404)

    dossier = dos_res.data

    try:
        inv_res = supabase.table("invullingen").select("*").eq("dossier_id", dossier_id).execute()
        invullingen_raw = inv_res.data or []
    except Exception:
        invullingen_raw = []

    # Enrich with template fields; skip verborgen
    invullingen = []
    for inv in invullingen_raw:
        if inv.get("extern_toegang", "verborgen") == "verborgen":
            continue
        try:
            tmpl_res = supabase.table("templates").select("*").eq("id", inv["template_id"]).single().execute()
            tmpl = tmpl_res.data or {}
        except Exception:
            tmpl = {}
        fields = tmpl.get("fields") or []
        if isinstance(fields, str):
            fields = json.loads(fields)
        waarden = inv.get("waarden") or {}
        if isinstance(waarden, str):
            waarden = json.loads(waarden)
        invullingen.append({
            **inv,
            "template": tmpl,
            "fields": fields,
            "waarden": waarden,
        })

    if request.method == "POST":
        errors = []
        # Process all invulbare invullingen
        for inv in invullingen:
            if inv["extern_toegang"] != "invulbaar":
                continue
            waarden = {}
            for field in inv["fields"]:
                key = field["name"]
                val = request.form.get(f"{inv['id']}_{key}", "").strip()
                if field.get("required") and not val:
                    errors.append(f'"{field.get("label", key)}" is verplicht.')
                waarden[key] = val

            if not errors:
                try:
                    supabase.table("invullingen").update({
                        "waarden": waarden,
                        "updated_at": datetime.utcnow().isoformat(),
                    }).eq("id", inv["id"]).execute()
                except Exception as e:
                    errors.append(f"Fout bij opslaan: {e}")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "dossier_extern.html",
                cfg=cfg,
                dossier=dossier,
                invullingen=invullingen,
                token=token,
                prefill=request.form,
            )

        return redirect(url_for("dossier_extern_bedankt", token_id=token_id))

    return render_template(
        "dossier_extern.html",
        cfg=cfg,
        dossier=dossier,
        invullingen=invullingen,
        token=token,
        prefill={},
    )


@app.route("/dossier/extern/<token_id>/bedankt")
def dossier_extern_bedankt(token_id):
    cfg = get_config()
    try:
        tok_res = supabase.table("dossier_tokens").select("dossier_id").eq("id", token_id).single().execute()
        if tok_res.data:
            dos_res = supabase.table("dossiers").select("naam").eq("id", tok_res.data["dossier_id"]).single().execute()
            dossier_naam = dos_res.data["naam"] if dos_res.data else ""
        else:
            dossier_naam = ""
    except Exception:
        dossier_naam = ""
    return render_template("dossier_extern_bedankt.html", cfg=cfg, dossier_naam=dossier_naam)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    cfg = get_config()
    return render_template("base.html", cfg=cfg, error="Pagina niet gevonden (404)"), 404


@app.errorhandler(500)
def server_error(e):
    cfg = get_config()
    return render_template("base.html", cfg=cfg, error="Interne serverfout (500)"), 500


if __name__ == "__main__":
    app.run(debug=True)
