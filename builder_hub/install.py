from builder.template_sync import sync_builder_templates


def after_install():
	_sync()


def after_migrate():
	_sync()


def _sync():
	# Import the hub's bundled template fixtures into this site's DB, published so
	# their routes resolve for public Preview. Reuses builder's importer pointed
	# at this app (builder imports nothing from builder_hub — no circular dep).
	sync_builder_templates(app="builder_hub", publish=True)
