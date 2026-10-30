frappe.ui.form.on("Hub Plugin", {
	refresh(form) {
		if (form.is_new() || !["Published", "Deprecated"].includes(form.doc.status)) {
			return;
		}

		form.add_custom_button(
			__("Check for New Releases"),
			() => {
				frappe
					.call({
						method: "builder_hub.plugins.api.request_release_check",
						args: { plugin_name: form.doc.name },
						freeze: true,
					})
					.then(() =>
						frappe.show_alert({
							message: __(
								"The release check is queued. Reload the form to see new releases."
							),
							indicator: "green",
						})
					);
			},
			__("Actions")
		);
	},
});
