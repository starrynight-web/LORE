from django.urls import path
from .views import (
    search_view, governed_query_view, test_groq_api_view,
    configurations_view, promote_configuration_view,
    rollback_configuration_view, optimization_runs_view
)

urlpatterns = [
    path('search/', search_view, name='retrieval-search'),
    path('query/', governed_query_view, name='retrieval-query'),
    path('test-groq/', test_groq_api_view, name='retrieval-test-groq'),
    path('configurations/', configurations_view, name='retrieval-configurations'),
    path('configurations/promote/', promote_configuration_view, name='retrieval-promote'),
    path('configurations/rollback/', rollback_configuration_view, name='retrieval-rollback'),
    path('optimizations/', optimization_runs_view, name='retrieval-optimizations'),
]
