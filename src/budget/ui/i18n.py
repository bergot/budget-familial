"""Langue : l'interface est en français uniquement."""

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator


def install_french(app: QCoreApplication) -> None:
    """Passe Qt en français : dates, nombres, et textes des boîtes de dialogue standard.

    Qt fournit ses propres traductions (« Annuler », « Copier »...) dans des fichiers `.qm`.
    Si elles sont introuvables, on garde l'anglais pour ces textes sans autre conséquence.
    """
    locale = QLocale(QLocale.Language.French, QLocale.Country.France)
    QLocale.setDefault(locale)

    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in ("qtbase",):
        translator = QTranslator(app)  # `app` devient son propriétaire : il reste en vie
        if translator.load(locale, name, "_", translations):
            app.installTranslator(translator)
