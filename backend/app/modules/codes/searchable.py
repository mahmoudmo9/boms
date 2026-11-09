"""Global search (v0.9.0): every record code (CS-…, SUP-CN-…, PRD-…, SH-…); an exact code ranks first."""
from app.modules.codes import service
from app.modules.search.registry import SearchProvider, register

register(SearchProvider(type="code", label_key="search.type.code", search=service.search, order=1))
