<script lang="ts">
	import { onMount } from 'svelte';
	import { Check, X, Key, Database, Zap, AlertCircle, Save } from 'lucide-svelte';
	import type { Settings } from '$lib/types';

	let settings: Settings = {
		finviz_api_key: '',
		groq_api_key: '',
		openrouter_api_key: '',
		finviz_portfolio_numbers: [],
		selected_models: [],
		theme: 'dark'
	};

	let loading = false;
	let saving = false;
	let validationResults: Record<string, { valid: boolean; message: string }> = {};
	let availableModels: any = {};

	onMount(async () => {
		await loadSettings();
		await loadAvailableModels();
	});

    async function loadSettings() {
		try {
            const response = await fetch('/api/settings/');
            if (!response.ok) {
                throw new Error('Failed to load settings');
            }
            const data = await response.json();
			
			settings = {
				finviz_api_key: data.finviz_configured ? '***configured***' : '',
				groq_api_key: data.groq_configured ? '***configured***' : '',
				openrouter_api_key: data.openrouter_configured ? '***configured***' : '',
				finviz_portfolio_numbers: data.finviz_portfolio_numbers || [],
				selected_models: data.selected_models || [],
				theme: data.theme || 'dark'
			};
		} catch (error) {
			console.error('Failed to load settings:', error);
		}
	}

	async function loadAvailableModels() {
		try {
			const response = await fetch('/api/settings/models/available');
			availableModels = await response.json();
		} catch (error) {
			console.error('Failed to load models:', error);
		}
	}

	async function validateApiKey(keyType: string, apiKey: string) {
		if (!apiKey || apiKey === '***configured***') return;

		loading = true;
		try {
			const response = await fetch('/api/settings/validate-key', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ key_type: keyType, api_key: apiKey })
			});

			if (!response.ok) {
				// For network/server errors, treat as deferred validation
				validationResults[keyType] = {
					valid: true,
					message: 'Could not verify key now. Will validate on first use.'
				};
				return;
			}

			const result = await response.json();
			validationResults[keyType] = result;
		} catch (error) {
			// For any errors, treat as deferred validation
			validationResults[keyType] = {
				valid: true,
				message: 'Could not verify key now. Will validate on first use.'
			};
		} finally {
			loading = false;
		}
	}

    async function saveSettings() {
		if (saving) return;
		saving = true;

		try {
			// Check if any API key validation has explicitly failed
			const hasFailedValidation = Object.values(validationResults).some(
				result => result && !result.valid && !result.message.includes('deferred') && !result.message.includes('Could not verify')
			);

			if (hasFailedValidation) {
				alert('Please fix validation errors before saving');
				return;
			}

			// Send only fields that changed; avoid sending masked secrets
			const payload: any = {
				finviz_portfolio_numbers: settings.finviz_portfolio_numbers,
				selected_models: settings.selected_models,
				theme: settings.theme
			};

			// Only include API keys that have been changed
			if (settings.finviz_api_key && settings.finviz_api_key !== '***configured***') {
				payload.finviz_api_key = settings.finviz_api_key;
			}
			if (settings.groq_api_key && settings.groq_api_key !== '***configured***') {
				payload.groq_api_key = settings.groq_api_key;
			}
			if (settings.openrouter_api_key && settings.openrouter_api_key !== '***configured***') {
				payload.openrouter_api_key = settings.openrouter_api_key;
			}

			console.log('Saving settings with payload:', payload);

			// First try with trailing slash
			console.log('Attempting to save settings with trailing slash...');
			let response = await fetch('/api/settings/', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
			});

			console.log('First attempt response:', {
				status: response.status,
				statusText: response.statusText,
				ok: response.ok
			});

			// If that fails, try without trailing slash
			if (!response.ok && response.status === 404) {
				console.log('First attempt failed with 404, trying without trailing slash...');
				response = await fetch('/api/settings', {
					method: 'PUT',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(payload)
				});

				console.log('Second attempt response:', {
					status: response.status,
					statusText: response.statusText,
					ok: response.ok
				});
			}

			if (!response.ok) {
				const errorData = await response.json().catch(() => {
					console.log('Failed to parse error response as JSON');
					return response.text().catch(() => null);
				});
				console.error('Failed to save settings:', {
					status: response.status,
					statusText: response.statusText,
					errorData
				});
				throw new Error(`Failed to save settings: ${response.status} - ${response.statusText}${errorData ? ` - ${JSON.stringify(errorData)}` : ''}`);
			}

			const result = await response.json();
			console.log('Settings saved:', result);

			// Show success message
			alert('Settings saved successfully!');
			await loadSettings();
		} catch (error) {
			console.error('Failed to save settings:', error);
			alert(`Failed to save settings: ${error.message || 'Unknown error'}`);
		} finally {
			saving = false;
		}
	}

	function addPortfolioNumber() {
		settings.finviz_portfolio_numbers = [...settings.finviz_portfolio_numbers, 0];
	}

	function removePortfolioNumber(index: number) {
		settings.finviz_portfolio_numbers = settings.finviz_portfolio_numbers.filter((_, i) => i !== index);
	}

    function toggleModel(modelId: string, provider: 'groq'|'openrouter') {
        const id = `${provider}:${modelId}`;
        if (settings.selected_models.includes(id)) {
            settings.selected_models = settings.selected_models.filter(m => m !== id);
        } else {
            settings.selected_models = [...settings.selected_models, id];
        }
    }
</script>

<div class="max-w-4xl mx-auto space-y-6">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-3xl font-bold text-gray-900 dark:text-white">Settings</h1>
			<p class="text-gray-600 dark:text-gray-400 mt-1">
				Configure API keys, models, and preferences
			</p>
		</div>
		<button
			class="btn-primary flex items-center gap-2"
			on:click={saveSettings}
			disabled={saving}
		>
			<Save class="h-4 w-4" />
			{saving ? 'Saving...' : 'Save Settings'}
		</button>
	</div>

	<!-- API Keys Section -->
	<div class="card p-6">
		<h2 class="text-xl font-semibold mb-4 flex items-center gap-2">
			<Key class="h-5 w-5" />
			API Keys
		</h2>

		<div class="space-y-4">
			<!-- Finviz API Key -->
			<div>
				<label for="finviz-api-key" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
					Finviz Elite API Key
				</label>
				<div class="flex gap-2">
					<input
						id="finviz-api-key"
						type="password"
						class="input flex-1"
						bind:value={settings.finviz_api_key}
						placeholder="Enter your Finviz Elite API key"
						on:blur={() => settings.finviz_api_key && validateApiKey('finviz', settings.finviz_api_key)}
					/>
					{#if validationResults.finviz}
						<div class="flex items-center">
							{#if validationResults.finviz.valid}
								<Check class="h-5 w-5 text-success-500" />
							{:else}
								<X class="h-5 w-5 text-danger-500" />
							{/if}
						</div>
					{/if}
				</div>
				{#if validationResults.finviz}
					<p class="text-xs mt-1 {validationResults.finviz.valid ? 'text-success-600 dark:text-success-400' : 'text-danger-600 dark:text-danger-400'}">
						{validationResults.finviz.message}
					</p>
				{/if}
			</div>

			<!-- Groq API Key -->
			<div>
				<label for="groq-api-key" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
					Groq API Key
				</label>
				<div class="flex gap-2">
					<input
						id="groq-api-key"
						type="password"
						class="input flex-1"
						bind:value={settings.groq_api_key}
						placeholder="Enter your Groq API key"
						on:blur={() => settings.groq_api_key && validateApiKey('groq', settings.groq_api_key)}
					/>
					{#if validationResults.groq}
						<div class="flex items-center">
							{#if validationResults.groq.valid}
								<Check class="h-5 w-5 text-success-500" />
							{:else}
								<X class="h-5 w-5 text-danger-500" />
							{/if}
						</div>
					{/if}
				</div>
				{#if validationResults.groq}
					<p class="text-xs mt-1 {validationResults.groq.valid ? 'text-success-600 dark:text-success-400' : 'text-danger-600 dark:text-danger-400'}">
						{validationResults.groq.message}
					</p>
				{/if}
			</div>

			<!-- OpenRouter API Key -->
			<div>
				<label for="openrouter-api-key" class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
					OpenRouter API Key
				</label>
				<div class="flex gap-2">
					<input
						id="openrouter-api-key"
						type="password"
						class="input flex-1"
						bind:value={settings.openrouter_api_key}
						placeholder="Enter your OpenRouter API key"
						on:blur={() => settings.openrouter_api_key && validateApiKey('openrouter', settings.openrouter_api_key)}
					/>
					{#if validationResults.openrouter}
						<div class="flex items-center">
							{#if validationResults.openrouter.valid}
								<Check class="h-5 w-5 text-success-500" />
							{:else}
								<X class="h-5 w-5 text-danger-500" />
							{/if}
						</div>
					{/if}
				</div>
				{#if validationResults.openrouter}
					<p class="text-xs mt-1 {validationResults.openrouter.valid ? 'text-success-600 dark:text-success-400' : 'text-danger-600 dark:text-danger-400'}">
						{validationResults.openrouter.message}
					</p>
				{/if}
			</div>
		</div>
	</div>

	<!-- Portfolio Configuration -->
	<div class="card p-6">
		<h2 class="text-xl font-semibold mb-4 flex items-center gap-2">
			<Database class="h-5 w-5" />
			Finviz Portfolios
		</h2>

		<div class="space-y-3">
			{#each settings.finviz_portfolio_numbers as portfolio, index}
				<div class="flex items-center gap-2">
					<input
						type="number"
						class="input w-32"
						bind:value={settings.finviz_portfolio_numbers[index]}
						placeholder="Portfolio ID"
					/>
					<button
						class="btn-danger py-1 px-2"
						on:click={() => removePortfolioNumber(index)}
					>
						<X class="h-4 w-4" />
					</button>
				</div>
			{/each}

			<button
				class="btn-secondary flex items-center gap-2"
				on:click={addPortfolioNumber}
			>
				<Database class="h-4 w-4" />
				Add Portfolio
			</button>
		</div>
	</div>

	<!-- Model Selection -->
	<div class="card p-6">
		<h2 class="text-xl font-semibold mb-4 flex items-center gap-2">
			<Zap class="h-5 w-5" />
			Sentiment Models
		</h2>

		{#if availableModels.models}
			<div class="space-y-4">
				<!-- Groq Models -->
				{#if availableModels.models.groq?.length > 0}
					<div>
						<h3 class="font-medium text-gray-900 dark:text-white mb-2">Groq Models</h3>
						<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {#each availableModels.models.groq as model}
								<label class="flex items-center gap-2 p-2 rounded-lg border border-gray-200 dark:border-dark-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-dark-800">
									<input
										type="checkbox"
                                    checked={settings.selected_models.includes(`groq:${model.id}`)}
                                    on:change={() => toggleModel(model.id, 'groq')}
										class="rounded"
									/>
									<span class="text-sm">{model.name}</span>
								</label>
							{/each}
						</div>
					</div>
				{/if}

				<!-- OpenRouter Models -->
				{#if availableModels.models.openrouter?.length > 0}
					<div>
						<h3 class="font-medium text-gray-900 dark:text-white mb-2">OpenRouter Models</h3>
						<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {#each availableModels.models.openrouter as model}
								<label class="flex items-center gap-2 p-2 rounded-lg border border-gray-200 dark:border-dark-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-dark-800">
									<input
										type="checkbox"
                                    checked={settings.selected_models.includes(`openrouter:${model.id}`)}
                                    on:change={() => toggleModel(model.id, 'openrouter')}
										class="rounded"
									/>
									<span class="text-sm">{model.name}</span>
								</label>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		{:else}
			<div class="text-center py-8">
				<AlertCircle class="h-12 w-12 text-gray-400 mx-auto mb-2" />
				<p class="text-gray-500 dark:text-gray-400">Configure API keys to see available models</p>
			</div>
		{/if}
	</div>

	<!-- Theme Selection -->
	<div class="card p-6">
		<h2 class="text-xl font-semibold mb-4">Appearance</h2>
		
		<div class="space-y-3">
			<label class="flex items-center gap-3">
				<input
					type="radio"
					bind:group={settings.theme}
					value="dark"
					class="text-primary-600"
				/>
				<span class="text-gray-700 dark:text-gray-300">Dark Theme (NYC Night Skyline)</span>
			</label>
			<label class="flex items-center gap-3">
				<input
					type="radio"
					bind:group={settings.theme}
					value="light"
					class="text-primary-600"
				/>
				<span class="text-gray-700 dark:text-gray-300">Light Theme (Snowy Mountain Range)</span>
			</label>
		</div>
	</div>
</div>
