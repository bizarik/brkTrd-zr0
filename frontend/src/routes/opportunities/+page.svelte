<script lang="ts">
	import { onMount } from 'svelte';
	import { TrendingUp, TrendingDown, Filter, RefreshCw, Zap, Target } from 'lucide-svelte';
	import OpportunityCard from '$lib/components/OpportunityCard.svelte';
	import { opportunities } from '$lib/stores/opportunities';

	let loading = false;
	let generating = false;
	let selectedType = '';
	let minScore = 0;
	let status = 'active';

	onMount(async () => {
		await loadOpportunities();
	});

	async function loadOpportunities() {
		loading = true;
		const filters = {
			status,
			opportunity_type: selectedType,
			min_score: minScore.toString()
		};
		
		await opportunities.fetch(filters);
		loading = false;
	}

	async function generateOpportunities() {
		generating = true;
		try {
			await opportunities.generate();
			await loadOpportunities();
		} catch (error) {
			console.error('Failed to generate opportunities:', error);
		}
		generating = false;
	}

	$: filteredOpportunities = $opportunities.filter(opp => {
		if (selectedType && opp.type !== selectedType) return false;
		if (opp.score < minScore) return false;
		return true;
	});

	$: longOpportunities = filteredOpportunities.filter(opp => opp.type === 'long');
	$: shortOpportunities = filteredOpportunities.filter(opp => opp.type === 'short');
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-3xl font-bold text-gray-900 dark:text-white">Trading Opportunities</h1>
			<p class="text-gray-600 dark:text-gray-400 mt-1">
				AI-powered trading signals with risk management
			</p>
		</div>
		<div class="flex items-center gap-2">
			<button
				class="btn-secondary flex items-center gap-2"
				on:click={loadOpportunities}
				disabled={loading}
			>
				<RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
				Refresh
			</button>
			<button
				class="btn-primary flex items-center gap-2"
				on:click={generateOpportunities}
				disabled={generating}
			>
				<Zap class="h-4 w-4 {generating ? 'animate-pulse' : ''}" />
				{generating ? 'Generating...' : 'Generate New'}
			</button>
		</div>
	</div>

	<!-- Stats -->
	<div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
		<div class="card p-4">
			<div class="flex items-center justify-between">
				<div>
					<p class="text-sm text-gray-600 dark:text-gray-400">Total Opportunities</p>
					<p class="text-2xl font-bold text-gray-900 dark:text-white">{filteredOpportunities.length}</p>
				</div>
				<Target class="h-8 w-8 text-primary-500" />
			</div>
		</div>

		<div class="card p-4">
			<div class="flex items-center justify-between">
				<div>
					<p class="text-sm text-gray-600 dark:text-gray-400">Long Signals</p>
					<p class="text-2xl font-bold text-success-600 dark:text-success-400">{longOpportunities.length}</p>
				</div>
				<TrendingUp class="h-8 w-8 text-success-500" />
			</div>
		</div>

		<div class="card p-4">
			<div class="flex items-center justify-between">
				<div>
					<p class="text-sm text-gray-600 dark:text-gray-400">Short Signals</p>
					<p class="text-2xl font-bold text-danger-600 dark:text-danger-400">{shortOpportunities.length}</p>
				</div>
				<TrendingDown class="h-8 w-8 text-danger-500" />
			</div>
		</div>
	</div>

	<!-- Filters -->
	<div class="card p-4">
		<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
			<!-- Type Filter -->
			<select class="input" bind:value={selectedType} on:change={loadOpportunities}>
				<option value="">All Types</option>
				<option value="long">Long Only</option>
				<option value="short">Short Only</option>
			</select>

			<!-- Status Filter -->
			<select class="input" bind:value={status} on:change={loadOpportunities}>
				<option value="active">Active</option>
				<option value="executed">Executed</option>
				<option value="expired">Expired</option>
				<option value="cancelled">Cancelled</option>
			</select>

			<!-- Min Score Filter -->
			<div class="flex items-center gap-2">
				<label class="text-sm text-gray-600 dark:text-gray-400">Min Score:</label>
				<input
					type="range"
					min="0"
					max="100"
					bind:value={minScore}
					on:input={loadOpportunities}
					class="flex-1"
				/>
				<span class="text-sm font-medium w-12">{minScore}</span>
			</div>
		</div>
	</div>

	<!-- Opportunities Grid -->
	{#if loading}
		<div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
			{#each Array(6) as _}
				<div class="card p-4">
					<div class="skeleton h-6 w-1/3 mb-2" />
					<div class="skeleton h-8 w-2/3 mb-4" />
					<div class="skeleton h-4 w-full mb-2" />
					<div class="skeleton h-4 w-3/4" />
				</div>
			{/each}
		</div>
	{:else if filteredOpportunities.length > 0}
		<div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
			{#each filteredOpportunities as opportunity}
				<OpportunityCard {opportunity} />
			{/each}
		</div>
	{:else}
		<div class="card p-8 text-center">
			<Target class="h-12 w-12 text-gray-400 mx-auto mb-4" />
			<h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">No Opportunities Found</h3>
			<p class="text-gray-600 dark:text-gray-400 mb-4">
				No trading opportunities match your current filters. Generate new opportunities or adjust your criteria.
			</p>
			<button class="btn-primary" on:click={generateOpportunities} disabled={generating}>
				<Zap class="h-4 w-4 mr-2" />
				Generate Opportunities
			</button>
		</div>
	{/if}
</div>
