/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class EmailRateLimitDashboard extends Component {
    static template = "odoo_email_rate_limit.EmailRateLimitDashboard";

    setup() {
        this.orm = useService("orm");
        this.state = useState({ loading: true, servers: [], organization: null, error: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.servers = await this.orm.call("ir.mail_server", "get_rate_limit_dashboard");
            this.state.organization = await this.orm.call("email.rate.limit.org.state", "get_dashboard_status");
        } catch (error) {
            this.state.error = error.message || String(error);
        } finally {
            this.state.loading = false;
        }
    }

    formatReset(value) {
        if (!value) return "—";
        return value.replace("T", " ") + " UTC";
    }
}

registry.category("actions").add("email_rate_limit_dashboard", EmailRateLimitDashboard);
