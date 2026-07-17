from __future__ import annotations

import pytest

from infrastructure.scrapers.portalinmobiliario import (
    classify_portal_page_state,
    extract_portal_detail_urls,
)
from scripts.portal_create_session import load_config, load_portal_env
from scripts.portal_detail_smoke import _sanitize_html as _sanitize_detail_html
from scripts.portal_smoke import _sanitize_html


def _workspace_env_file():
    path = __import__("pathlib").Path(".pytest_tmp_portal_smoke_env") / "portal.env"
    path.parent.mkdir(exist_ok=True)
    return path


def test_load_portal_env_reads_key_values():
    env_file = _workspace_env_file()
    env_file.write_text(
        "\n".join(
            [
                "PORTALINMOBILIARIO_EMAIL=user@example.com",
                "PORTALINMOBILIARIO_PASSWORD=example-password",
                "PORTAL_STORAGE_STATE_PATH=.local/example_storage_state.json",
                "PORTAL_SMOKE_SEARCH_URL=https://www.portalinmobiliario.com/venta/departamento/",
            ]
        ),
        encoding="utf-8",
    )

    values = load_portal_env(env_file)

    assert values["PORTALINMOBILIARIO_EMAIL"] == "user@example.com"
    assert values["PORTALINMOBILIARIO_PASSWORD"] == "example-password"
    assert values["PORTAL_STORAGE_STATE_PATH"] == ".local/example_storage_state.json"
    assert values["PORTAL_SMOKE_SEARCH_URL"].startswith("https://www.portalinmobiliario.com/")


def test_load_config_requires_credentials(monkeypatch):
    monkeypatch.delenv("PORTALINMOBILIARIO_EMAIL", raising=False)
    monkeypatch.delenv("PORTALINMOBILIARIO_PASSWORD", raising=False)
    env_file = _workspace_env_file()
    env_file.write_text("PORTAL_STORAGE_STATE_PATH=.local/example_storage_state.json\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        load_config(env_file)


def test_classify_portal_page_state_distinguishes_blockers():
    assert classify_portal_page_state("<html></html>", status_code=403) == "blocked"
    assert classify_portal_page_state("<html></html>", status_code=429) == "blocked"
    assert (
        classify_portal_page_state("<html><input type='email'><input type='password'>Iniciar sesion</html>")
        == "login_page"
    )
    assert classify_portal_page_state("<html><body>Verifica tu cuenta</body></html>") == "verification_visible"


def test_recaptcha_script_without_visible_challenge_is_not_captcha():
    html = """
    <html><head>
      <script src="https://www.google.com/recaptcha/api.js"></script>
      <script>window.challenge = "loaded";</script>
    </head><body>Portal Inmobiliario</body></html>
    """

    assert classify_portal_page_state(html) == "homepage"


def test_visible_captcha_iframe_is_captcha():
    html = """
    <html><body>
      <iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>
    </body></html>
    """

    assert classify_portal_page_state(html) == "captcha_visible"


def test_homepage_is_classified_as_homepage():
    html = "<html><body><h1>Portal Inmobiliario</h1><button>Comprar</button><button>Arrendar</button></body></html>"

    assert classify_portal_page_state(html) == "homepage"


def test_classify_portal_page_state_detects_results():
    html = """
    <html><body>
      <ol>
        <li class="ui-search-layout__item">
          <div class="poly-card">
            <a class="poly-component__title" href="/MLC-1">Depto</a>
          </div>
        </li>
      </ol>
    </body></html>
    """

    assert classify_portal_page_state(html) == "authenticated"


def test_classify_results_before_passive_login_links():
    html = """
    <html><body>
      <a href="/login">Iniciar sesión</a>
      <ol>
        <li class="ui-search-layout__item">
          <div class="poly-card">
            <a class="poly-component__title" href="/MLC-1">Depto</a>
          </div>
        </li>
      </ol>
    </body></html>
    """

    assert classify_portal_page_state(html) == "authenticated"


def test_extract_portal_detail_urls_limits_and_deduplicates():
    html = """
    <li class="ui-search-layout__item"><a class="poly-component__title" href="/MLC-1">A</a></li>
    <li class="ui-search-layout__item"><a class="poly-component__link" href="/MLC-1">A dup</a></li>
    <li class="ui-search-layout__item"><a class="poly-component__title" href="/MLC-2">B</a></li>
    <li class="ui-search-layout__item"><a class="poly-component__title" href="/MLC-3">C</a></li>
    """

    urls = extract_portal_detail_urls(html, base_url="https://www.portalinmobiliario.com/search", limit=2)

    assert urls == [
        "https://www.portalinmobiliario.com/MLC-1",
        "https://www.portalinmobiliario.com/MLC-2",
    ]


def test_sanitize_html_keeps_result_cards_and_removes_scripts():
    html = """
    <html><head><script>secret()</script></head><body>
      <li class="ui-search-layout__item"><div class="poly-card">
        <a class="poly-component__title" href="/MLC-1#tracking">Depto</a>
      </div></li>
    </body></html>
    """

    sanitized = _sanitize_html(html)

    assert "secret()" not in sanitized
    assert "ui-search-layout__item" in sanitized
    assert 'href="/MLC-1"' in sanitized


def test_detail_sanitize_keeps_json_ld_and_removes_sensitive_state():
    html = """
    <html><body>
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Depto",
         "productID":"MLC123","offers":{"price":3139,"priceCurrency":"CLF"}}
      </script>
      <script id="__NORDIC_RENDERING_CTX__">
        _n.ctx.r={"appProps":{"pageProps":{"initialState":{
          "id":"MLC123",
          "csrfToken":"secret-token",
          "d2id":"secret-d2id",
          "components":{"short_description":[{"id":"header","title":"Depto"}]}
        }}}};
      </script>
      <script>const token = "remove-me";</script>
    </body></html>
    """

    sanitized = _sanitize_detail_html(html)

    assert "application/ld+json" in sanitized
    assert "__NORDIC_RENDERING_CTX__" in sanitized
    assert "secret-token" not in sanitized
    assert "secret-d2id" not in sanitized
    assert "remove-me" not in sanitized
