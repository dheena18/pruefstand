"""Parts of the Gesetze-im-Internet (GII) XML loader (T2.2).

``safezip`` reads the downloaded ``xml.zip`` without extracting it, ``xmlparse`` parses the
untrusted XML with a hardened parser, ``norms`` decides which ``<norm>`` is a citable unit,
``extract`` turns its content into text, ``keys`` builds the citation key and ``stats`` counts
what happened. The public entry point is :class:`pruefstand.ingest.gii_xml.GiiXmlLoader`.
"""
