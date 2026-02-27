<script>
    import {onMount} from "svelte";
    import {session} from "../stores/session.js";
    import {api} from "../utils/api.js";
    import FolderOpen from "@lucide/svelte/icons/folder-open";
    import ChevronUp from "@lucide/svelte/icons/chevron-up";
    import RefreshCw from "@lucide/svelte/icons/refresh-cw";

    let rootPath = "";
    let sandboxBase = "";
    let currentPath = "";
    let parentPath = null;
    let directories = [];
    let loading = false;
    let browsing = false;
    let browseError = "";
    let validationMessage = "";
    let validationValid = false;

    async function loadDirectory(path = "") {
        browsing = true;
        browseError = "";
        try {
            const response = await api.config.browseLocalDirectories(path);
            currentPath = response.current_path;
            sandboxBase = response.sandbox_base || sandboxBase;
            parentPath = response.parent_path;
            directories = response.directories || [];
        } catch (e) {
            browseError = e.message || "Failed to browse directories";
            directories = [];
        } finally {
            browsing = false;
        }
    }

    function selectFolder(path) {
        rootPath = path;
        validationValid = false;
        validationMessage = `Selected: ${path}`;
    }

    onMount(async () => {
        try {
            const localConfig = await api.config.getLocalConfig();
            rootPath = localConfig.root_path || "";
            sandboxBase = localConfig.sandbox_base || "";
            validationValid = !!localConfig.validated;
            validationMessage = localConfig.validated ? "Configured" : "";

            await loadDirectory(rootPath || sandboxBase);
            if (!rootPath) {
                rootPath = currentPath || sandboxBase || "/media";
                if (!validationMessage) {
                    validationMessage = `Selected: ${rootPath}`;
                }
            }
        } catch (e) {
            console.error("Failed to load local config:", e);
            try {
                await loadDirectory(sandboxBase || "/media");
                rootPath = currentPath || sandboxBase || "/media";
                validationMessage = `Selected: ${rootPath}`;
            } catch (browseErr) {
                console.error("Failed to load default local directory:", browseErr);
            }
        }
    });

    async function verifyAndContinue() {
        loading = true;
        validationMessage = "";
        validationValid = false;
        try {
            const response = await api.config.setupLocal(rootPath.trim());
            if (!response.success) {
                validationMessage = response.errors?.local || response.message || "Validation failed";
                return;
            }

            validationValid = true;
            validationMessage = "Configured";
            await session.loadActiveSession();
        } catch (e) {
            validationMessage = e.message || "Validation failed";
        } finally {
            loading = false;
        }
    }
</script>

<div class="local-setup-container">
    <div class="setup-header">
        <div class="header-icon">
            <FolderOpen size="48"/>
        </div>
        <h1>Local Source Setup</h1>
        <p class="required-label">REQUIRED</p>
    </div>

    <div class="setup-card">
        <p class="field-label">Choose Mounted Root Folder</p>
        <p class="hint">Sandbox base: <code>{sandboxBase || "(loading...)"}</code></p>

        <div class="browser-controls">
            <button
                    class="btn btn-cancel btn-sm"
                    on:click={() => parentPath && loadDirectory(parentPath)}
                    disabled={loading || browsing || !parentPath}
            >
                <ChevronUp size="14"/>
                Up
            </button>
            <button
                    class="btn btn-cancel btn-sm"
                    on:click={() => loadDirectory(currentPath || sandboxBase)}
                    disabled={loading || browsing}
            >
                <RefreshCw size="14"/>
                Refresh
            </button>
            <button
                    class="btn btn-verify btn-sm"
                    on:click={() => selectFolder(currentPath)}
                    disabled={loading || browsing || !currentPath}
            >
                Use Current Folder
            </button>
        </div>

        <div class="current-path"><code>{currentPath || "(loading...)"}</code></div>

        {#if browseError}
            <div class="validation error">{browseError}</div>
        {/if}

        <div class="folder-list">
            {#if browsing}
                <div class="folder-empty">Loading folders...</div>
            {:else if directories.length === 0}
                <div class="folder-empty">No subfolders found.</div>
            {:else}
                {#each directories as directory}
                    <div class="folder-row">
                        <button
                                class="folder-open"
                                on:click={() => loadDirectory(directory.path)}
                                disabled={loading || browsing}
                        >
                            {directory.name}
                        </button>
                        <button
                                class="btn btn-cancel btn-sm"
                                on:click={() => selectFolder(directory.path)}
                                disabled={loading || browsing}
                        >
                            Select
                        </button>
                    </div>
                {/each}
            {/if}
        </div>

        <div class="selected-path">
            Selected folder: <code>{rootPath || "(none)"}</code>
        </div>

        {#if validationMessage}
            <div class:success={validationValid} class:error={!validationValid} class="validation">
                {validationMessage}
            </div>
        {/if}
    </div>

    <div class="actions">
        <button class="btn btn-verify" on:click={verifyAndContinue} disabled={loading || !rootPath.trim()}>
            {#if loading}
                <span class="btn-spinner"></span>
                Verifying...
            {:else}
                Continue
            {/if}
        </button>
    </div>
</div>

<style>
    .local-setup-container {
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

    .setup-card {
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 1rem;
        display: grid;
        gap: 0.75rem;
    }

    .field-label {
        margin: 0;
        font-weight: 600;
        color: var(--text-primary);
    }

    .browser-controls {
        display: flex;
        gap: 0.5rem;
        flex-wrap: wrap;
    }

    .current-path,
    .selected-path {
        font-size: 0.9rem;
    }

    .folder-list {
        border: 1px solid var(--border-color);
        border-radius: 8px;
        background: var(--bg-primary);
        max-height: 300px;
        overflow: auto;
    }

    .folder-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.5rem;
        padding: 0.45rem 0.55rem;
        border-bottom: 1px solid var(--border-color);
    }

    .folder-row:last-child {
        border-bottom: none;
    }

    .folder-open {
        border: none;
        background: transparent;
        color: var(--text-primary);
        text-align: left;
        cursor: pointer;
        padding: 0.2rem 0.25rem;
        flex: 1;
    }

    .folder-open:hover {
        color: var(--accent-1);
    }

    .folder-empty {
        padding: 0.8rem;
        color: var(--text-secondary);
        font-size: 0.9rem;
    }

    .hint {
        margin: 0;
        color: var(--text-secondary);
        font-size: 0.85rem;
    }

    .validation {
        font-size: 0.9rem;
    }

    .validation.success {
        color: var(--success);
    }

    .validation.error {
        color: var(--danger);
    }

    .actions {
        margin-top: 1.25rem;
        display: flex;
        justify-content: flex-end;
    }
</style>
