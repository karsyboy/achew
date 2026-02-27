<script>
    import {onMount} from "svelte";
    import {session} from "../stores/session.js";
    import {api} from "../utils/api.js";
    import Workflow from "@lucide/svelte/icons/workflow";

    let selectedMode = "local";
    let loading = false;
    let error = "";

    onMount(async () => {
        try {
            const response = await api.config.getSourceMode();
            if (response.mode && response.mode !== "unset") {
                selectedMode = response.mode;
            }
        } catch (e) {
            console.error("Failed to load source mode:", e);
        }
    });

    async function continueSetup() {
        loading = true;
        error = "";
        try {
            const response = await api.config.setupSource(selectedMode);
            if (!response.success) {
                error = response.message || "Failed to save source mode";
                return;
            }
            await session.loadActiveSession();
        } catch (e) {
            error = e.message || "Failed to save source mode";
        } finally {
            loading = false;
        }
    }
</script>

<div class="source-setup-container">
    <div class="setup-header">
        <div class="header-icon">
            <Workflow size="48"/>
        </div>
        <h1>Select Source Mode</h1>
        <p class="required-label">REQUIRED</p>
    </div>

    <div class="mode-options">
        <label class="mode-option" class:selected={selectedMode === "abs"}>
            <input type="radio" bind:group={selectedMode} value="abs"/>
            <div>
                <h3>Audiobookshelf</h3>
                <p>Use Audiobookshelf for discovery and chapter write-back.</p>
            </div>
        </label>

        <label class="mode-option" class:selected={selectedMode === "local"}>
            <input type="radio" bind:group={selectedMode} value="local"/>
            <div>
                <h3>Local Directory</h3>
                <p>Use the mounted `/media` folder for local file discovery and write-back.</p>
            </div>
        </label>
    </div>

    {#if error}
        <div class="alert alert-danger">{error}</div>
    {/if}

    <div class="actions">
        <button class="btn btn-verify" on:click={continueSetup} disabled={loading}>
            {#if loading}
                <span class="btn-spinner"></span>
                Saving...
            {:else}
                Continue
            {/if}
        </button>
    </div>
</div>

<style>
    .source-setup-container {
        max-width: 700px;
        margin: 0 auto;
    }

    .setup-header {
        text-align: center;
        margin-bottom: 2rem;
    }

    .header-icon {
        margin-bottom: 1rem;
        color: var(--accent-1);
    }

    .required-label {
        color: var(--warning);
        font-weight: 700;
        font-size: 0.75rem;
        letter-spacing: 0.1em;
    }

    .mode-options {
        display: grid;
        gap: 1rem;
    }

    .mode-option {
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 1rem;
        display: grid;
        grid-template-columns: auto 1fr;
        gap: 0.75rem;
        cursor: pointer;
    }

    .mode-option.selected {
        border-color: var(--accent-1);
        background: color-mix(in srgb, var(--accent-1) 12%, transparent);
    }

    .mode-option h3 {
        margin: 0 0 0.25rem 0;
    }

    .mode-option p {
        margin: 0;
        color: var(--text-secondary);
    }

    .actions {
        margin-top: 1.5rem;
        display: flex;
        justify-content: flex-end;
    }
</style>
