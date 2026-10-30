// //// Neoffice — added file (no upstream equivalent): the buttons of a hub block, which is drawn in the Builder editor.
// The preview window: the block as a page, in a frame as wide as a desktop, a tablet or a phone, with the look of a palette and sample words.
function openPreview(frm) {
	frappe.call({ method: "builder_hub.blocks.preview_options" }).then((o) => {
		const options = o.message;
		let draw = () => {};
		const dialog = new frappe.ui.Dialog({
			title: __("Preview of {0}", [frm.doc.block_id]),
			size: "extra-large",
			fields: [
				{
					fieldname: "palette",
					fieldtype: "Select",
					label: __("Look of the site"),
					options: options.palettes.map((p) => ({ value: p.value, label: p.label })),
					default: options.default_palette,
					onchange: () => draw(),
				},
				{ fieldname: "lang", fieldtype: "Select", label: __("Sample words"), options: options.languages.join("\n"), default: "fr", onchange: () => draw() },
				{ fieldtype: "Column Break" },
				{
					fieldname: "length",
					fieldtype: "Select",
					label: __("Length of the texts"),
					options: options.lengths.join("\n"),
					default: "longest",
					description: __("Longest: as long as each slot allows, where a layout breaks first"),
					onchange: () => draw(),
				},
				{ fieldname: "device", fieldtype: "Select", label: __("Width"), options: Object.keys(options.devices).join("\n"), default: "desktop", onchange: () => draw() },
				{ fieldtype: "Section Break" },
				{ fieldname: "frame", fieldtype: "HTML" },
			],
		});
		draw = () => {
			const v = dialog.get_values(true) || {};
			const device = v.device || "desktop";
			frm.call("preview_html", { palette: v.palette, lang: v.lang, length: v.length }).then((r) => {
				const width = options.devices[device];
				const frame = document.createElement("iframe");
				frame.setAttribute("sandbox", "");
				frame.srcdoc = r.message;
				frame.style.cssText = `width:${width}px;max-width:100%;height:68vh;border:1px solid var(--border-color);border-radius:8px;background:#fff;display:block;margin:0 auto`;
				dialog.fields_dict.frame.$wrapper.empty().append(frame);
			});
		};
		dialog.show();
		draw();
	});
}

frappe.ui.form.on("Hub Block", {
	refresh(frm) {
		if (frm.is_new()) return;
		// not "Block": the desk translates it as the verb (Bloquer)
		const group = __("Editor");
		frm.add_custom_button(__("Preview"), () => (frm.is_dirty() ? frm.save().then(() => openPreview(frm)) : openPreview(frm)), group);
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
