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
	let hoursFilter = 168; // 7 days
	let tickerOptions: Array<{ ticker: string; company: string }> = [];
	let selectedPortfolio = '';
	let sortBy = 'newest'; // Default sort
	let pageSize = 50; // Number of headlines to display

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
			hours: hoursFilter.toString(),
			limit: pageSize.toString()
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
			// Get IDs of headlines currently visible on the page that don't have sentiment yet
			const headlinesToAnalyze = sortedHeadlines
				.filter(h => !h.sentiment) // Only headlines without sentiment analysis
				.map(h => h.id);
			
			if (headlinesToAnalyze.length === 0) {
				alert('All visible headlines already have sentiment analysis!');
				loading = false;
				return;
			}
			
			// Confirm with user
			const confirmed = confirm(
				`Analyze ${headlinesToAnalyze.length} headline(s) currently visible on this page?\n\n` +
				`This will use API credits based on your selected models.`
			);
			
			if (!confirmed) {
				loading = false;
				return;
			}
			
			// Trigger sentiment analysis for specific headlines
			const response = await fetch('/api/sentiment/analyze/batch', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ headline_ids: headlinesToAnalyze })
			});
			
			const result = await response.json();
			
			// Wait for analysis to process
			await new Promise((r) => setTimeout(r, 2000));
			
			// Reload headlines to show updated sentiment
			await loadHeadlines();
			
			alert(`Analysis initiated for ${result.count || headlinesToAnalyze.length} headline(s)!`);
		} catch (e) {
			console.error('Failed to analyze sentiment:', e);
			alert('Failed to analyze sentiment. Please try again.');
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

	$: unanalyzedCount = sortedHeadlines.filter(h => !h.sentiment).length;
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
				disabled={loading || unanalyzedCount === 0}
				title="Analyze sentiment for headlines currently visible on this page"
			>
				<Brain class="h-4 w-4" />
				{#if unanalyzedCount > 0}
					Analyze Visible ({unanalyzedCount})
				{:else}
					All Analyzed ✓
				{/if}
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
				<option value={2}>Last 2 Hours</option>
				<option value={4}>Last 4 Hours</option>
				<option value={8}>Last 8 Hours</option>
				<option value={12}>Last 12 Hours</option>
				<option value={6}>Last 6 Hours</option>
				<option value={24}>Last 24 Hours</option>
				<option value={36}>Last 36 Hours</option>
				<option value={48}>Last 48 Hours</option>
				<option value={72}>Last 3 Days</option>
				<option value={168}>Last Week</option>
			</select>

			<!-- Portfolio picker for fetch -->
			<input class="input" placeholder="Portfolio ID (optional)" bind:value={selectedPortfolio} />
		</div>
		
		<!-- Sort and Page Size Controls -->
		<div class="mt-4 flex flex-wrap items-center gap-4">
			<div class="flex items-center gap-2">
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
			
			<div class="flex items-center gap-2">
				<span class="text-sm font-medium text-gray-700 dark:text-gray-300">Show:</span>
				<select class="input w-32" bind:value={pageSize} on:change={loadHeadlines} aria-label="Headlines per page">
					<option value={50}>50</option>
					<option value={100}>100</option>
					<option value={200}>200</option>
					<option value={500}>500</option>
					<option value={1000}>1000</option>
				</select>
				<span class="text-sm text-gray-600 dark:text-gray-400">headlines</span>
			</div>
			
			<div class="text-sm text-gray-600 dark:text-gray-400 ml-auto">
				Showing {sortedHeadlines.length} of {$headlines.length} headlines
			</div>
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
