<script lang="ts">
	import { onMount } from 'svelte';
	import { Search, Filter, RefreshCw, ExternalLink, Brain } from 'lucide-svelte';
	import HeadlineCard from '$lib/components/HeadlineCard.svelte';
	import { headlines, fetchTickers } from '$lib/stores/headlines';

	let loading = false;
	let searchTerm = '';
	let selectedTicker = '';
	let selectedSector = '';
	let selectedSource = '';
	let hoursFilter = 24;
	let tickerOptions: Array<{ ticker: string; company: string }> = [];
	let selectedPortfolio = '';
	let sortBy = 'newest'; // Default sort

	onMount(async () => {
		await loadTickers();
		await loadHeadlines();
		// If empty, trigger a server fetch then reload
		if (!$headlines.length) {
			await triggerFetch();
			await new Promise((r) => setTimeout(r, 1200));
			await loadHeadlines();
		}
	});

	async function triggerFetch() {
		try {
			const pid = selectedPortfolio || '';
			const url = pid ? `/api/headlines/fetch?portfolio_id=${encodeURIComponent(pid)}` : '/api/headlines/fetch';
			await fetch(url, { method: 'POST' });
		} catch (e) {
			console.error('Failed to trigger fetch:', e);
		}
	}

	async function loadTickers() {
		tickerOptions = await fetchTickers();
	}

	async function loadHeadlines() {
		loading = true;
		const filters: any = {
			ticker: selectedTicker,
			sector: selectedSector,
			source: selectedSource,
			hours: hoursFilter.toString()
		};
		const pid = (selectedPortfolio || '').trim();
		if (pid && /^\d+$/.test(pid)) filters.portfolio_id = pid;
		
		await headlines.fetch(filters);
		loading = false;
	}

	async function handleRefresh() {
		loading = true;
		await triggerFetch();
		await new Promise((r) => setTimeout(r, 1200));
		await loadHeadlines();
		loading = false;
	}

	async function analyzeSentiment() {
		loading = true;
		try {
			// Trigger sentiment analysis for recent headlines
			await fetch('/api/sentiment/analyze/recent?hours=24', { method: 'POST' });
			// Wait a bit for analysis to start
			await new Promise((r) => setTimeout(r, 2000));
			// Reload headlines to show any updated sentiment
			await loadHeadlines();
		} catch (e) {
			console.error('Failed to analyze sentiment:', e);
		}
		loading = false;
	}

	$: filteredHeadlines = $headlines.filter(headline => {
		if (searchTerm && !headline.headline.toLowerCase().includes(searchTerm.toLowerCase())) {
			return false;
		}
		return true;
	});

	$: sortedHeadlines = [...filteredHeadlines].sort((a, b) => {
		switch (sortBy) {
			case 'newest':
				return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
			case 'oldest':
				return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
			case 'ticker-asc':
				return a.ticker.localeCompare(b.ticker);
			case 'ticker-desc':
				return b.ticker.localeCompare(a.ticker);
			case 'source-asc':
				return a.source.localeCompare(b.source);
			case 'source-desc':
				return b.source.localeCompare(a.source);
			default:
				return 0;
		}
	});
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-3xl font-bold text-gray-900 dark:text-white">Headlines</h1>
			<p class="text-gray-600 dark:text-gray-400 mt-1">
				Real-time news headlines with sentiment analysis
			</p>
		</div>
		<div class="flex gap-2">
			<button
				class="btn-secondary flex items-center gap-2"
				on:click={analyzeSentiment}
				disabled={loading}
			>
				<Brain class="h-4 w-4" />
				Analyze Sentiment
			</button>
			<button
				class="btn-primary flex items-center gap-2"
				on:click={handleRefresh}
				disabled={loading}
			>
				<RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
				Refresh
			</button>
		</div>
	</div>

	<!-- Filters -->
	<div class="card p-4">
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
			<!-- Search -->
			<div class="relative">
				<Search class="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
				<input
					type="text"
					class="input pl-10"
					placeholder="Search headlines..."
					bind:value={searchTerm}
				/>
			</div>

			<!-- Ticker Filter -->
			<select class="input" bind:value={selectedTicker} on:change={loadHeadlines}>
				<option value="">All Tickers</option>
				{#each tickerOptions as opt}
					<option value={opt.ticker}>{opt.ticker} — {opt.company}</option>
				{/each}
			</select>

			<!-- Sector Filter -->
			<select class="input" bind:value={selectedSector} on:change={loadHeadlines}>
				<option value="">All Sectors</option>
				<option value="Technology">Technology</option>
				<option value="Healthcare">Healthcare</option>
				<option value="Finance">Finance</option>
				<option value="Energy">Energy</option>
			</select>

			<!-- Time Filter -->
			<select class="input" bind:value={hoursFilter} on:change={loadHeadlines}>
				<option value={1}>Last Hour</option>
				<option value={6}>Last 6 Hours</option>
				<option value={24}>Last 24 Hours</option>
				<option value={72}>Last 3 Days</option>
				<option value={168}>Last Week</option>
			</select>

			<!-- Portfolio picker for fetch -->
			<input class="input" placeholder="Portfolio ID (optional)" bind:value={selectedPortfolio} />
		</div>
		
		<!-- Sort Dropdown -->
		<div class="mt-4 flex items-center gap-2">
			<Filter class="h-4 w-4 text-gray-500" />
			<span class="text-sm font-medium text-gray-700 dark:text-gray-300">Sort by:</span>
			<select class="input w-48" bind:value={sortBy} aria-label="Sort headlines by">
				<option value="newest">Newest First</option>
				<option value="oldest">Oldest First</option>
				<option value="ticker-asc">Ticker (A → Z)</option>
				<option value="ticker-desc">Ticker (Z → A)</option>
				<option value="source-asc">Source (A → Z)</option>
				<option value="source-desc">Source (Z → A)</option>
			</select>
		</div>
	</div>

	<!-- Headlines List -->
	<div class="space-y-4">
		{#if loading}
			<div class="space-y-3">
				{#each Array(10) as _}
					<div class="card p-4">
						<div class="skeleton h-6 w-3/4 mb-2" />
						<div class="skeleton h-4 w-1/2" />
					</div>
				{/each}
			</div>
		{:else if sortedHeadlines.length > 0}
			<div class="space-y-3">
				{#each sortedHeadlines as headline}
					<HeadlineCard {headline} />
				{/each}
			</div>
		{:else}
			<div class="card p-8 text-center">
				<ExternalLink class="h-12 w-12 text-gray-400 mx-auto mb-4" />
				<h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">No Headlines Found</h3>
				<p class="text-gray-600 dark:text-gray-400 mb-4">
					No headlines match your current filters. Try adjusting your search criteria or refresh to fetch new headlines.
				</p>
				<button class="btn-primary" on:click={handleRefresh}>
					Fetch Headlines
				</button>
			</div>
		{/if}
	</div>
</div>
