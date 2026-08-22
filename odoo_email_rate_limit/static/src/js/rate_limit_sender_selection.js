/** @odoo-module **/

import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";
import { SelectionField, selectionField } from "@web/views/fields/selection/selection_field";
import { registry } from "@web/core/registry";

export class RateLimitSenderSelectionField extends SelectionField {
    static template = "odoo_email_rate_limit.RateLimitSenderSelectionField";

    setup() {
        super.setup();
        this.orm = useService("orm");
        // SelectionField renders before onOpened can refresh the choices. Never
        // expose null/undefined to the SelectMenu because its template calls
        // Array.from() on the options collection.
        this.rateLimitState = useState({ choices: [] });
    }

    get options() {
        if (this.props.name === "rate_limit_sender") {
            const choices = this.rateLimitState.choices;
            return Array.isArray(choices) ? choices : [];
        }
        const options = super.options;
        return options ?? [];
    }

    async refreshRateLimitChoices() {
        if (this.props.name !== "rate_limit_sender") {
            return;
        }
        const choices = await this.orm.call(
            "mail.template",
            "get_rate_limit_sender_selection",
            []
        );
        this.rateLimitState.choices = Array.isArray(choices) ? choices : [];
    }

    async onSenderDropdownOpened() {
        await this.refreshRateLimitChoices();
    }
}

export const rateLimitSenderSelectionField = {
    ...selectionField,
    component: RateLimitSenderSelectionField,
};

registry.category("fields").add("rate_limit_sender", rateLimitSenderSelectionField);
