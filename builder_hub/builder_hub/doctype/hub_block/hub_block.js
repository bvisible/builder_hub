// //// Neoffice — added file (no upstream equivalent): the buttons of a hub block, which is drawn in the Builder editor.
frappe.ui.form.on("Hub Block", {
	refresh(frm) {
		if (frm.is_new()) return;
		// not "Block": the desk translates it as the verb (Bloquer)
		const group = __("Editor");
		frm.add_custom_button(
			__("Draw in the editor"),
			() => {
				const open = () =>
					frm.call("draw_page").then((r) => {
						window.open(`/builder/page/${r.message}`, "_blank");
						frm.reload_doc();
					});
				frm.is_dirty() ? frm.save().then(open) : open();
			},
			group,
		);
		if (frm.doc.source_page) {
			frm.add_custom_button(
				__("Compile from the page"),
				() => {
					const compile = () =>
						frm.call("compile_from_page").then((r) => {
							frm.reload_doc();
							const report = (r.message && r.message.report) || "";
							frappe.msgprint({
								title: __("Compiled, version {0}", [r.message.version]),
								message: report ? `<pre style="white-space:pre-wrap">${frappe.utils.escape_html(report)}</pre>` : __("No error, no warning."),
								indicator: /ERROR/.test(report) ? "red" : "green",
							});
						});
					frm.is_dirty() ? frm.save().then(compile) : compile();
				},
				group,
			);
			frm.add_custom_button(__("Open the page in the editor"), () => window.open(`/builder/page/${frm.doc.source_page}`, "_blank"), group);
		}
	},
});
