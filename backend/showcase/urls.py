"""HighSpeed API routes."""
from __future__ import annotations

from django.urls import path

from showcase import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("engine", views.engine_status, name="engine"),
    path("stats", views.StatsView.as_view(), name="stats"),
    path("usecases", views.UseCaseListView.as_view(), name="usecases"),
    path("usecases/<str:key>", views.UseCaseDetailView.as_view(), name="usecase-detail"),
    path("usecases/<str:key>/run", views.RunUseCaseView.as_view(), name="usecase-run"),
    path("usecases/<str:key>/export.csv", views.ExportCsvView.as_view(), name="usecase-export"),
    path("runs/all", views.RunAllView.as_view(), name="run-all"),
    path("runs/latest", views.LatestRunView.as_view(), name="run-latest"),
    path("runs/<int:pk>", views.RunView.as_view(), name="run-detail"),
    path("actions/reseed", views.ReseedView.as_view(), name="reseed"),
    path("policy", views.PolicyView.as_view(), name="policy"),
    path("policy/activate/<int:version>", views.PolicyActivateView.as_view(), name="policy-activate"),
    path("feedback", views.FeedbackView.as_view(), name="feedback"),
    path("learning", views.LearningView.as_view(), name="learning"),
    path("learning/refit", views.LearningRefitView.as_view(), name="learning-refit"),
    path("learning/apply", views.LearningApplyView.as_view(), name="learning-apply"),
    path("learning/export", views.LearningExportView.as_view(), name="learning-export"),
]
