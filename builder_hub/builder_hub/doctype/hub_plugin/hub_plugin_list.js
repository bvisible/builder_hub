frappe.listview_settings["Hub Plugin"] = {
	onload(listview) {
		if (!frappe.user.has_role(["System Manager", "Builder Hub Maintainer"])) {
			return;
		}

		listview.page.add_inner_button(__("Add from GitHub"), () => {
			frappe.prompt(
				{
					fieldname: "repository_url",
					fieldtype: "Data",
					label: __("GitHub Repository URL"),
					reqd: 1,
				},
				({ repository_url }) => confirm_plugin(repository_url),
				__("Add Plugin from GitHub"),
				__("Check Repository")
			);
		});
	},
};

function confirm_plugin(repository_url) {
	call_plugin_method("preview_plugin", repository_url).then(({ message }) => {
		frappe.confirm(
			__("Publish {0} {1} by {2}?", [
				message.plugin_name.bold(),
				message.version,
				message.publisher_id,
			]),
			() =>
				call_plugin_method("add_plugin", repository_url, { expected: message }).then(
					({ message }) => frappe.set_route("Form", "Hub Plugin", message.plugin)
				)
		);
	});
}

function call_plugin_method(method, repository_url, args = {}) {
	return frappe.call({
		method: `builder_hub.plugins.api.${method}`,
		args: { repository_url, ...args },
		freeze: true,
	});
}
