<script lang="ts">
	import { onMount } from 'svelte';
	import {
		TrendingUp,
		TrendingDown,
		Activity,
		Clock,
		AlertCircle,
		ChevronRight,
		ArrowUpRight,
		ArrowDownRight,
		RefreshCw,
		Wifi,
		WifiOff
	} from 'lucide-svelte';
	import HeadlineCard from '$lib/components/HeadlineCard.svelte';
	import OpportunityCard from '$lib/components/OpportunityCard.svelte';
	import SentimentChart from '$lib/components/SentimentChart.svelte';
	import SentimentScatterplot from '$lib/components/SentimentScatterplot.svelte';
	import D3SentimentScatterplot from '$lib/components/D3SentimentScatterplot.svelte';
	import SvgSentimentScatterplot from '$lib/components/SvgSentimentScatterplot.svelte';
	import WordCloud from '$lib/components/WordCloud.svelte';
	import { headlines } from '$lib/stores/headlines';
	import { opportunities } from '$lib/stores/opportunities';
	import { analytics } from '$lib/stores/analytics';
	import { websocket } from '$lib/stores/websocket';

	let loading = true;
	let error: string | null = null;
	let stats = {
		totalHeadlines: 0,
		avgSentiment: 0,
		avgConfidence: 0,
		modelConsensus: 0,
		topMovers: [],
		activeOpportunities: 0
	};

	async function loadDashboardData() {
		try {
			loading = true;
			error = null;
			
			// Fetch all data in parallel
			const [headlinesData, opportunitiesData, analyticsData] = await Promise.all([
				headlines.fetch().catch(e => { console.error('Headlines fetch failed:', e); return []; }),
				opportunities.fetch().catch(e => { console.error('Opportunities fetch failed:', e); return []; }),
				Promise.all([
					analytics.fetchSummary().catch(e => { console.error('Analytics summary failed:', e); return null; }),
					analytics.fetchTopMovers().catch(e => { console.error('Top movers failed:', e); return null; }),
					analytics.fetchTrends({ days: 7 }).catch(e => { console.error('Trends failed:', e); return null; })
				])
			]);
			
			// Calculate comprehensive stats
			updateStats();
			
		} catch (e) {
			console.error('Failed to load dashboard data:', e);
			error = 'Failed to load dashboard data. Please try refreshing the page.';
		} finally {
			loading = false;
		}
	}

	function updateStats() {
		stats.totalHeadlines = $headlines.length;
		stats.activeOpportunities = $opportunities.filter(o => o.status === 'active').length;
		
		// Calculate average sentiment from headlines
		const headlinesWithSentiment = $headlines.filter(h => h.sentiment);
		if (headlinesWithSentiment.length > 0) {
			const totalSentiment = headlinesWithSentiment.reduce((sum, h) => sum + (h.sentiment?.avg_sentiment || 0), 0);
			const totalConfidence = headlinesWithSentiment.reduce((sum, h) => sum + (h.sentiment?.avg_confidence || 0), 0);
			stats.avgSentiment = totalSentiment / headlinesWithSentiment.length;
			stats.avgConfidence = totalConfidence / headlinesWithSentiment.length;
			
			// Calculate model consensus (how much models agree)
			const consensusScores = headlinesWithSentiment.map(h => {
				if (h.sentiment?.model_votes && h.sentiment.model_votes.length > 1) {
					const sentiments = h.sentiment.model_votes.map(m => m.sentiment);
					const avg = sentiments.reduce((a, b) => a + b, 0) / sentiments.length;
					const variance = sentiments.reduce((sum, s) => sum + Math.pow(s - avg, 2), 0) / sentiments.length;
					return 1 - Math.sqrt(variance); // Higher consensus = lower variance
				}
				return 1; // Single model = perfect consensus
			});
			stats.modelConsensus = consensusScores.reduce((a, b) => a + b, 0) / consensusScores.length;
		}
		
		stats.topMovers = $analytics.topMovers || [];
	}

	onMount(() => {
		loadDashboardData();
		
		// Set up periodic refresh every 5 minutes (reduced from 30 seconds)
		const interval = setInterval(() => {
			if (!loading) {
				loadDashboardData();
			}
		}, 300000);
		
		// Subscribe to WebSocket updates for real-time data
		const unsubscribeWs = websocket.subscribe(($ws) => {
			if ($ws.lastMessage) {
				const message = $ws.lastMessage;
				
				// Handle different types of real-time updates (throttled to reduce refresh frequency)
				if (message.type === 'headline') {
					// Refresh stats when new headlines arrive (reduced frequency)
					setTimeout(updateStats, 2000);
				} else if (message.type === 'opportunity') {
					// Refresh stats when new opportunities arrive (reduced frequency)
					setTimeout(updateStats, 2000);
				} else if (message.type === 'analytics_update') {
					// Refresh analytics data (throttled)
					setTimeout(() => {
						analytics.fetchSummary();
						analytics.fetchTopMovers();
					}, 1000);
				}
			}
		});
		
		return () => {
			clearInterval(interval);
			unsubscribeWs();
		};
	});

	// Reactive updates when store data changes
	$: if ($headlines || $opportunities || $analytics) {
		updateStats();
	}

	$: latestHeadlines = $headlines.slice(0, 5);
	$: topOpportunities = $opportunities.slice(0, 3);
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
		<div>
			<h1 class="text-2xl lg:text-3xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
			<p class="text-gray-600 dark:text-gray-400 mt-1 text-sm lg:text-base">
				Real-time market sentiment and trading opportunities
			</p>
		</div>
		<div class="flex flex-wrap items-center gap-2 lg:gap-4">
			<!-- Connection Status -->
			<div class="flex items-center space-x-2 text-sm">
				{#if $websocket.connected}
					<Wifi class="h-4 w-4 text-success-500" />
					<span class="text-success-600 dark:text-success-400 hidden sm:inline">Connected</span>
				{:else}
					<WifiOff class="h-4 w-4 text-danger-500" />
					<span class="text-danger-600 dark:text-danger-400 hidden sm:inline">Disconnected</span>
				{/if}
			</div>
			
			<!-- Refresh Button -->
			<button 
				on:click={loadDashboardData}
				disabled={loading}
				class="flex items-center space-x-2 px-3 py-2 text-sm bg-primary-600 hover:bg-primary-700 disabled:bg-primary-400 text-white rounded-lg transition-colors"
			>
				<RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
				<span class="hidden sm:inline">{loading ? 'Refreshing...' : 'Refresh'}</span>
			</button>
			
			<!-- Current Time -->
			<div class="flex items-center space-x-2 text-sm text-gray-600 dark:text-gray-400">
				<Clock class="h-4 w-4" />
				<span class="hidden md:inline">{new Date().toLocaleTimeString()}</span>
			</div>
		</div>
	</div>

	<!-- Error Display -->
	{#if error}
		<div class="card p-4 bg-danger-50 dark:bg-danger-900/20 border-danger-200 dark:border-danger-800">
			<div class="flex items-center space-x-2">
				<AlertCircle class="h-5 w-5 text-danger-600 dark:text-danger-400" />
				<p class="text-danger-700 dark:text-danger-300">{error}</p>
				<button 
					on:click={() => error = null}
					class="ml-auto text-danger-600 hover:text-danger-700 dark:text-danger-400 dark:hover:text-danger-300"
				>
					×
				</button>
			</div>
		</div>
	{/if}

	<!-- Stats Grid -->
	<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4">
		<div class="card p-4 lg:p-6">
			<div class="flex items-center justify-between">
				<div>
					<p class="text-xs lg:text-sm text-gray-600 dark:text-gray-400">Headlines Today</p>
					<p class="text-xl lg:text-2xl font-bold mt-1">{stats.totalHeadlines}</p>
				</div>
				<div class="p-2 lg:p-3 rounded-lg bg-blue-100 dark:bg-blue-900/30">
					<Activity class="h-5 w-5 lg:h-6 lg:w-6 text-blue-600 dark:text-blue-400" />
				</div>
			</div>
		</div>

		<div class="card p-4 lg:p-6">
			<div class="flex items-center justify-between">
				<div>
					<p class="text-xs lg:text-sm text-gray-600 dark:text-gray-400">Active Opportunities</p>
					<p class="text-xl lg:text-2xl font-bold mt-1">{stats.activeOpportunities}</p>
				</div>
				<div class="p-2 lg:p-3 rounded-lg bg-success-100 dark:bg-success-900/30">
					<TrendingUp class="h-5 w-5 lg:h-6 lg:w-6 text-success-600 dark:text-success-400" />
				</div>
			</div>
		</div>

		<div class="card p-4 lg:p-6">
			<div class="flex items-center justify-between">
				<div>
					<p class="text-xs lg:text-sm text-gray-600 dark:text-gray-400">Avg Sentiment</p>
					<p class="text-lg lg:text-2xl font-bold mt-1 {stats.avgSentiment > 0 ? 'sentiment-positive' : stats.avgSentiment < 0 ? 'sentiment-negative' : 'sentiment-neutral'}">
						{stats.avgSentiment > 0 ? '+' : ''}{(stats.avgSentiment * 100).toFixed(1)}%
					</p>
				</div>
				<div class="p-2 lg:p-3 rounded-lg {stats.avgSentiment > 0 ? 'bg-success-100 dark:bg-success-900/30' : stats.avgSentiment < 0 ? 'bg-danger-100 dark:bg-danger-900/30' : 'bg-blue-100 dark:bg-blue-900/30'}">
					{#if stats.avgSentiment > 0}
						<ArrowUpRight class="h-5 w-5 lg:h-6 lg:w-6 text-success-600 dark:text-success-400" />
					{:else if stats.avgSentiment < 0}
						<ArrowDownRight class="h-5 w-5 lg:h-6 lg:w-6 text-danger-600 dark:text-danger-400" />
					{:else}
						<Activity class="h-5 w-5 lg:h-6 lg:w-6 text-blue-600 dark:text-blue-400" />
					{/if}
				</div>
			</div>
		</div>

		<div class="card p-4 lg:p-6">
			<div class="flex items-center justify-between">
				<div>
					<p class="text-xs lg:text-sm text-gray-600 dark:text-gray-400">Model Consensus</p>
					<p class="text-xl lg:text-2xl font-bold mt-1">{(stats.modelConsensus * 100).toFixed(0)}%</p>
					<p class="text-xs text-gray-500 dark:text-gray-400 mt-1 hidden lg:block">
						Avg Confidence: {(stats.avgConfidence * 100).toFixed(0)}%
					</p>
				</div>
				<div class="p-2 lg:p-3 rounded-lg {stats.modelConsensus > 0.8 ? 'bg-success-100 dark:bg-success-900/30' : stats.modelConsensus > 0.6 ? 'bg-warning-100 dark:bg-warning-900/30' : 'bg-danger-100 dark:bg-danger-900/30'}">
					<AlertCircle class="h-5 w-5 lg:h-6 lg:w-6 {stats.modelConsensus > 0.8 ? 'text-success-600 dark:text-success-400' : stats.modelConsensus > 0.6 ? 'text-warning-600 dark:text-warning-400' : 'text-danger-600 dark:text-danger-400'}" />
				</div>
			</div>
		</div>
	</div>

	<!-- Main Content Grid -->
	<div class="grid grid-cols-1 xl:grid-cols-3 gap-4 lg:gap-6">
		<!-- Latest Headlines -->
		<div class="xl:col-span-2 space-y-4">
			<div class="flex items-center justify-between">
				<h2 class="text-xl font-semibold">Latest Headlines</h2>
				<a href="/headlines" class="text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 flex items-center">
					View all
					<ChevronRight class="h-4 w-4 ml-1" />
				</a>
			</div>

			{#if loading}
				<div class="space-y-3">
					{#each Array(5) as _}
						<div class="card p-4">
							<div class="skeleton h-6 w-3/4 mb-2" />
							<div class="skeleton h-4 w-1/2" />
						</div>
					{/each}
				</div>
			{:else if latestHeadlines.length > 0}
				<div class="space-y-3">
					{#each latestHeadlines as headline}
						<HeadlineCard {headline} />
					{/each}
				</div>
			{:else}
				<div class="card p-8 text-center">
					<p class="text-gray-500 dark:text-gray-400">No headlines available</p>
				</div>
			{/if}
		</div>

		<!-- Trading Opportunities -->
		<div class="space-y-4">
			<div class="flex items-center justify-between">
				<h2 class="text-xl font-semibold">Top Opportunities</h2>
				<a href="/opportunities" class="text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 flex items-center">
					View all
					<ChevronRight class="h-4 w-4 ml-1" />
				</a>
			</div>

			{#if loading}
				<div class="space-y-3">
					{#each Array(3) as _}
						<div class="card p-4">
							<div class="skeleton h-5 w-1/3 mb-2" />
							<div class="skeleton h-6 w-2/3 mb-2" />
							<div class="skeleton h-4 w-full" />
						</div>
					{/each}
				</div>
			{:else if topOpportunities.length > 0}
				<div class="space-y-3">
					{#each topOpportunities as opportunity}
						<OpportunityCard {opportunity} compact={true} />
					{/each}
				</div>
			{:else}
				<div class="card p-8 text-center">
					<p class="text-gray-500 dark:text-gray-400">No opportunities available</p>
				</div>
			{/if}
		</div>
	</div>

	<!-- Analytics Section -->
	<div class="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6">
		<!-- Sentiment Trend Chart -->
		<div class="card p-6">
			<h3 class="text-lg font-semibold mb-4">Sentiment Trend</h3>
			<SentimentChart />
		</div>

		<!-- Sentiment Scatterplot -->
		<div class="card p-6">
			<SentimentScatterplot />
		</div>
	</div>

	<!-- Scatterplot Comparison -->
	<div class="grid grid-cols-1 xl:grid-cols-2 gap-4 lg:gap-6">
		<!-- D3 Scatterplot -->
		<div class="card p-6">
			<D3SentimentScatterplot />
		</div>
		
		<!-- SVG Scatterplot -->
		<div class="card p-6">
			<SvgSentimentScatterplot />
		</div>
	</div>

	<!-- Word Cloud Section -->
	<div class="grid grid-cols-1 gap-4 lg:gap-6">
		<!-- Word Cloud -->
		<div class="card p-6">
			<h3 class="text-lg font-semibold mb-4">Trending Terms</h3>
			<WordCloud />
		</div>
	</div>

	<!-- Top Movers -->
	<div class="card p-6">
		<div class="flex items-center justify-between mb-4">
			<h3 class="text-lg font-semibold">Top Movers</h3>
			<div class="flex items-center space-x-2">
				<select 
					class="text-sm border border-gray-300 dark:border-dark-600 rounded px-2 py-1 bg-white dark:bg-dark-800"
				on:change={(e) => {
					const sortBy = e.target?.value;
					// Could implement sorting logic here
					console.log('Sort by:', sortBy);
				}}
				>
					<option value="sentiment">By Sentiment</option>
					<option value="volume">By Volume</option>
					<option value="headlines">By Headlines</option>
				</select>
			</div>
		</div>
		
		{#if loading}
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
				{#each Array(6) as _}
					<div class="skeleton h-20" />
				{/each}
			</div>
		{:else if $analytics.topMovers && $analytics.topMovers.length > 0}
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
				{#each $analytics.topMovers as mover, index}
					<div class="group relative overflow-hidden rounded-lg bg-gradient-to-r from-gray-50 to-gray-100 dark:from-dark-800 dark:to-dark-700 p-4 hover:shadow-lg transition-all duration-300">
						<!-- Rank indicator -->
						<div class="absolute top-2 left-2 w-6 h-6 bg-primary-500 text-white text-xs font-bold rounded-full flex items-center justify-center">
							{index + 1}
						</div>
						
						<!-- Sentiment bar -->
						<div class="absolute top-0 right-0 w-1 h-full {mover.avg_sentiment > 0 ? 'bg-success-500' : mover.avg_sentiment < 0 ? 'bg-danger-500' : 'bg-gray-400'}"></div>
						
						<div class="flex items-start justify-between ml-8">
							<div class="flex-1">
								<p class="font-bold text-lg">{mover.ticker}</p>
								<p class="text-sm text-gray-600 dark:text-gray-400 truncate" title={mover.company || mover.ticker}>
									{mover.company || mover.ticker}
								</p>
								<div class="flex items-center space-x-2 mt-2 text-xs">
									<span class="px-2 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-full">
										{mover.headline_count} news
									</span>
									{#if mover.sector}
										<span class="px-2 py-1 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded-full">
											{mover.sector}
										</span>
									{/if}
								</div>
							</div>
							
							<div class="text-right">
								<div class="text-xl font-bold {mover.avg_sentiment > 0.2 ? 'text-success-600 dark:text-success-400' : mover.avg_sentiment < -0.2 ? 'text-danger-600 dark:text-danger-400' : 'text-blue-600 dark:text-blue-400'}">
									{mover.avg_sentiment > 0 ? '+' : ''}{(mover.avg_sentiment * 100).toFixed(1)}%
								</div>
								{#if mover.avg_confidence}
									<div class="text-xs text-gray-500 dark:text-gray-400">
										{(mover.avg_confidence * 100).toFixed(0)}% conf
									</div>
								{/if}
								{#if mover.price_change}
									<div class="text-xs mt-1 {mover.price_change > 0 ? 'text-success-600' : 'text-danger-600'}">
										{mover.price_change > 0 ? '+' : ''}{mover.price_change.toFixed(2)}%
									</div>
								{/if}
							</div>
						</div>
						
						<!-- Hover details -->
						<div class="absolute inset-0 bg-black bg-opacity-90 text-white p-4 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex flex-col justify-center">
							<h4 class="font-bold text-lg mb-2">{mover.ticker}</h4>
							<div class="space-y-1 text-sm">
								<div>Sentiment: {mover.avg_sentiment > 0 ? '+' : ''}{(mover.avg_sentiment * 100).toFixed(1)}%</div>
								<div>Headlines: {mover.headline_count}</div>
								{#if mover.avg_confidence}
									<div>Confidence: {(mover.avg_confidence * 100).toFixed(0)}%</div>
								{/if}
								{#if mover.latest_headline}
									<div class="mt-2 text-xs text-gray-300 italic">
										"{mover.latest_headline.substring(0, 80)}..."
									</div>
								{/if}
							</div>
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<div class="text-center py-8">
				<p class="text-gray-500 dark:text-gray-400">No top movers data available</p>
				<button 
					class="btn-secondary mt-2 text-sm"
					on:click={() => analytics.fetchTopMovers()}
				>
					Refresh Data
				</button>
			</div>
		{/if}
	</div>
</div>
