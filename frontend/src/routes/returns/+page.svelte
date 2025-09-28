<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import {
		TrendingUp,
		TrendingDown,
		BarChart,
		RefreshCw,
		Clock,
		Filter
	} from 'lucide-svelte';
	import type { PageData } from './$types';
	import { websocket } from '$lib/stores/websocket';
	import ReturnCell from '$lib/components/ReturnCell.svelte';
	import SentimentReturnsChart from '$lib/components/SentimentReturnsChart.svelte';
	import HistoricalReturnsChart from '$lib/components/HistoricalReturnsChart.svelte';

	let loading = true;
	let error: string | null = null;
	let activeTab: 'historical' | 'sentiment' = 'sentiment';
	let selectedTicker: string | null = null;
	let timeframe: string = '7d';
	let minConfidence: number = 0.6;

	// Data stores
	let sentimentReturns: any[] = [];
	let historicalReturns: any[] = [];

	onMount(async () => {
		await loadData();
		loading = false;
	});

	async function loadData() {
		try {
			if (selectedTicker) {
				const [sentimentRes, historicalRes] = await Promise.all([
					fetch(`/api/returns/sentiment/ticker/${selectedTicker}?days=${timeframe === '7d' ? 7 : 30}&min_confidence=${minConfidence}`),
					fetch(`/api/returns/historical/${selectedTicker}?days=${timeframe === '7d' ? 7 : 30}`)
				]);

				if (!sentimentRes.ok || !historicalRes.ok) {
					throw new Error('Failed to fetch data');
				}

				const sentimentData = await sentimentRes.json();
				const historicalData = await historicalRes.json();

				sentimentReturns = sentimentData.sentiment_returns;
				historicalReturns = historicalData.returns;
			}
		} catch (e) {
			console.error('Error loading data:', e);
			error = 'Failed to load data';
		}
	}

	function handleTickerSelect(event: Event) {
		selectedTicker = (event.target as HTMLSelectElement).value;
		loadData();
	}

	function handleTimeframeChange(newTimeframe: string) {
		timeframe = newTimeframe;
		loadData();
	}

	function handleConfidenceChange(event: Event) {
		minConfidence = parseFloat((event.target as HTMLInputElement).value);
		loadData();
	}

	$: {
		// Reactive statement to handle websocket updates
		if ($websocket.data?.type === 'new_sentiment') {
			loadData();
		}
	}
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-gray-900 dark:text-gray-100">Returns Analysis</h1>
		<div class="flex items-center space-x-4">
			<div class="flex items-center space-x-2">
				<label for="ticker-select" class="sr-only">Select Ticker</label>
				<select
					id="ticker-select"
					class="rounded-lg border border-gray-300 dark:border-dark-700 bg-white dark:bg-dark-800 px-3 py-2"
					on:change={handleTickerSelect}
				>
					<option value="">Select Ticker</option>
					<!-- Add ticker options dynamically -->
				</select>
			</div>

			<div class="flex items-center space-x-2 rounded-lg border border-gray-300 dark:border-dark-700 p-1">
				<button
					class="px-3 py-1 rounded-md transition-colors {timeframe === '7d'
						? 'bg-primary-100 text-primary-900 dark:bg-primary-900/30 dark:text-primary-300'
						: 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-dark-800'}"
					on:click={() => handleTimeframeChange('7d')}
				>
					7D
				</button>
				<button
					class="px-3 py-1 rounded-md transition-colors {timeframe === '30d'
						? 'bg-primary-100 text-primary-900 dark:bg-primary-900/30 dark:text-primary-300'
						: 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-dark-800'}"
					on:click={() => handleTimeframeChange('30d')}
				>
					30D
				</button>
			</div>
		</div>
	</div>

	<!-- Tabs -->
	<div class="border-b border-gray-200 dark:border-dark-700">
		<nav class="-mb-px flex space-x-8">
			<button
				class="whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium transition-colors {activeTab === 'sentiment'
					? 'border-primary-500 text-primary-600 dark:text-primary-400'
					: 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'}"
				on:click={() => (activeTab = 'sentiment')}
			>
				Sentiment Returns
			</button>
			<button
				class="whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium transition-colors {activeTab === 'historical'
					? 'border-primary-500 text-primary-600 dark:text-primary-400'
					: 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'}"
				on:click={() => (activeTab = 'historical')}
			>
				Historical Returns
			</button>
		</nav>
	</div>

	<!-- Content -->
	{#if loading}
		<div class="flex items-center justify-center py-12">
			<RefreshCw class="h-8 w-8 animate-spin text-primary-500" />
		</div>
	{:else if error}
		<div class="rounded-lg bg-danger-50 dark:bg-danger-900/30 p-4 text-danger-700 dark:text-danger-400">
			{error}
		</div>
	{:else if !selectedTicker}
		<div class="text-center py-12 text-gray-500 dark:text-gray-400">
			Select a ticker to view returns analysis
		</div>
	{:else if activeTab === 'sentiment'}
		<div class="space-y-6">
			<!-- Sentiment Returns Controls -->
			<div class="flex items-center space-x-4">
				<div class="flex items-center space-x-2">
					<label for="confidence-range" class="text-sm text-gray-700 dark:text-gray-300">Min Confidence:</label>
					<input
						id="confidence-range"
						type="range"
						min="0"
						max="1"
						step="0.1"
						value={minConfidence}
						on:change={handleConfidenceChange}
						class="w-32"
					/>
					<span class="text-sm text-gray-600 dark:text-gray-400">{minConfidence}</span>
				</div>
			</div>

			<!-- Sentiment Returns Chart -->
			<div class="rounded-lg border border-gray-200 dark:border-dark-700 bg-white dark:bg-dark-800 p-4">
				<SentimentReturnsChart data={sentimentReturns} timeframe={timeframe} />
			</div>

			<!-- Sentiment Returns Table -->
			<div class="rounded-lg border border-gray-200 dark:border-dark-700 bg-white dark:bg-dark-800 overflow-hidden">
				<table class="min-w-full divide-y divide-gray-200 dark:divide-dark-700">
					<thead class="bg-gray-50 dark:bg-dark-850">
						<tr>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Date
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Headline
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Sentiment
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								3h
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								24h
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Next Day
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								2d
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								3d
							</th>
						</tr>
					</thead>
					<tbody class="bg-white dark:bg-dark-800 divide-y divide-gray-200 dark:divide-dark-700">
						{#each sentimentReturns as row}
							<tr class="hover:bg-gray-50 dark:hover:bg-dark-750">
								<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
									{new Date(row.timestamp).toLocaleDateString()}
								</td>
								<td class="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">
									{row.headline}
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<div class="flex items-center space-x-2">
										<span
											class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {row.sentiment.value > 0
												? 'bg-success-100 text-success-800 dark:bg-success-900/30 dark:text-success-400'
												: row.sentiment.value < 0
												? 'bg-danger-100 text-danger-800 dark:bg-danger-900/30 dark:text-danger-400'
												: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200'}"
										>
											{row.sentiment.value > 0
												? 'Positive'
												: row.sentiment.value < 0
												? 'Negative'
												: 'Neutral'}
										</span>
										<span class="text-gray-500 dark:text-gray-400">
											({(row.sentiment.confidence * 100).toFixed(1)}%)
										</span>
									</div>
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns['3h']} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns['24h']} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns.next_day} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns['2d']} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns['3d']} />
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{:else}
		<div class="space-y-6">
			<!-- Historical Returns Chart -->
			<div class="rounded-lg border border-gray-200 dark:border-dark-700 bg-white dark:bg-dark-800 p-4">
				<HistoricalReturnsChart data={historicalReturns} />
			</div>

			<!-- Historical Returns Table -->
			<div class="rounded-lg border border-gray-200 dark:border-dark-700 bg-white dark:bg-dark-800 overflow-hidden">
				<table class="min-w-full divide-y divide-gray-200 dark:divide-dark-700">
					<thead class="bg-gray-50 dark:bg-dark-850">
						<tr>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Date
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Return
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Volume
							</th>
						</tr>
					</thead>
					<tbody class="bg-white dark:bg-dark-800 divide-y divide-gray-200 dark:divide-dark-700">
						{#each historicalReturns as row}
							<tr class="hover:bg-gray-50 dark:hover:bg-dark-750">
								<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
									{new Date(row.date).toLocaleDateString()}
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.return} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
									{row.volume.toLocaleString()}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>
