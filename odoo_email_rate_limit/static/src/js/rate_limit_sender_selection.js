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
        this.rateLimitState = useState({ choices: null });
    }

    get options() {
        if (this.props.name === "rate_limit_sender" && this.rateLimitState.choices) {
            return this.rateLimitState.choices.filter((option) => option[1] !== "");
        }
        return super.options;
    }

    async refreshRateLimitChoices() {
        if (this.props.name !== "rate_limit_sender") {
            return;
        }
        this.rateLimitState.choices = await this.orm.call(
            "mail.template",
            "get_rate_limit_sender_selection",
            []
        );
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
