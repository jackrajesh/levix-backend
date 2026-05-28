from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.pages import router


client_app = FastAPI()
client_app.include_router(router)
client = TestClient(client_app)


def test_sitemap_xml_response_headers_and_body():
    response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    assert response.content.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert b"<urlset" in response.content
    assert b"https://levixapp.in/" in response.content
    assert b"https://levixapp.in/login" not in response.content
    assert b"https://levixapp.in/register" not in response.content


def test_sitemap_xml_head_response_headers():
    response = client.head("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    assert response.headers["content-length"] == str(len(client.get("/sitemap.xml").content))


def test_robots_txt_references_public_sitemap():
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert "Sitemap: https://levixapp.in/sitemap.xml" in response.text
    assert "Disallow: /dashboard" in response.text
    assert "Disallow: /api" in response.text
    assert "Disallow: /login" in response.text
