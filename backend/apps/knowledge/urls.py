from django.urls import path
from .views import graph_overview_view

urlpatterns = [
    path('graph-overview/', graph_overview_view, name='knowledge-graph-overview'),
]

