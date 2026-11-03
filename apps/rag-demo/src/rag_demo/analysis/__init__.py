"""German text analysis for the sparse retrieval leg (T3.3).

Modules: ``normalise`` (NFC, folding, tokeniser, numbers), ``abbreviations`` (function-abbreviation
table), ``compound`` (dictionary compound splitter), ``analyzer`` (``GermanAnalyzer``) and
``sparse`` (``SparseEncoder``). Import from the submodules; this package re-exports nothing so that
``python -m rag_demo.analysis.analyzer`` runs without a double import.
"""
