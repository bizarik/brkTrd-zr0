<script lang="ts">
	import { onMount } from 'svelte';
	import {
		Database,
		Play,
		Table2,
		FileText,
		Download,
		Copy,
		Check,
		AlertCircle,
		ChevronRight,
		ChevronDown,
		Search
	} from 'lucide-svelte';

	let tables: any[] = [];
	let selectedTable: string | null = null;
	let tableDetails: any = null;
	let expandedTables: Set<string> = new Set();
	let sqlQuery = '';
	let queryResult: any = null;
	let queryError: string | null = null;
	let executing = false;
	let copied = false;
	let searchTerm = '';

	// Sample queries
	const sampleQueries = [
		{
			name: 'Recent Headlines',
			query: 'SELECT ticker, headline, headline_timestamp FROM headlines ORDER BY headline_timestamp DESC LIMIT 10;'
		},
		{
			name: 'Sentiment Analysis',
			query: 'SELECT h.ticker, h.headline, sa.avg_sentiment, sa.avg_confidence FROM headlines h JOIN sentiment_aggregates sa ON h.id = sa.headline_id ORDER BY h.headline_timestamp DESC LIMIT 10;'
		},
		{
			name: 'Portfolio Holdings',
			query: 'SELECT ticker, company, sector, industry, price, change FROM portfolio_holdings ORDER BY ticker;'
		},
		{
			name: 'Headlines by Ticker',
			query: 'SELECT ticker, COUNT(*) as count FROM headlines WHERE is_duplicate = FALSE GROUP BY ticker ORDER BY count DESC LIMIT 20;'
		}
	];

	onMount(async () => {
		await loadTables();
	});

	async function loadTables() {
		try {
			const response = await fetch('/api/database/schema');
			const data = await response.json();
			tables = data.tables.map((t: any) => ({
				name: t.name,
				count: t.row_count,
				columns: t.columns,
				primaryKeys: t.primary_keys,
				foreignKeys: t.foreign_keys
			}));
		} catch (error) {
			console.error('Failed to load tables:', error);
			queryError = 'Failed to load database schema';
		}
	}

	function toggleTableExpansion(tableName: string) {
		if (expandedTables.has(tableName)) {
			expandedTables.delete(tableName);
		} else {
			expandedTables.add(tableName);
		}
		expandedTables = new Set(expandedTables);
	}

	function loadSampleQuery(query: string) {
		sqlQuery = query;
	}

	async function executeQuery() {
		if (!sqlQuery.trim()) return;

		executing = true;
		queryError = null;
		queryResult = null;

		try {
			const response = await fetch('/api/database/query', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({ sql: sqlQuery })
			});

			const data = await response.json();

			if (!response.ok) {
				throw new Error(data.detail || 'Query execution failed');
			}

			queryResult = data.rows;
		} catch (error: any) {
			queryError = error.message || 'Failed to execute query';
		} finally {
			executing = false;
		}
	}

	function copyQuery() {
		navigator.clipboard.writeText(sqlQuery);
		copied = true;
		setTimeout(() => {
			copied = false;
		}, 2000);
	}

	function downloadResults() {
		if (!queryResult) return;
		
		// Convert results to CSV
		const csv = convertToCSV(queryResult);
		const blob = new Blob([csv], { type: 'text/csv' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'query_results.csv';
		a.click();
		URL.revokeObjectURL(url);
	}

	function convertToCSV(data: any): string {
		if (!data || !data.length) return '';
		
		const headers = Object.keys(data[0]);
		const rows = data.map((row: any) => 
			headers.map(header => JSON.stringify(row[header] || '')).join(',')
		);
		
		return [headers.join(','), ...rows].join('\n');
	}

	$: filteredTables = tables.filter(table => 
		table.name.toLowerCase().includes(searchTerm.toLowerCase())
	);
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-3xl font-bold text-gray-900 dark:text-white">Database Explorer</h1>
			<p class="text-gray-600 dark:text-gray-400 mt-1">
				Query and explore your database schema
			</p>
		</div>
	</div>

	<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
		<!-- Left Column: Schema Browser -->
		<div class="lg:col-span-1 space-y-4">
			<!-- Tables List -->
			<div class="card p-4">
				<div class="flex items-center gap-2 mb-4">
					<Database class="h-5 w-5 text-primary-500" />
					<h2 class="text-lg font-semibold">Database Schema</h2>
				</div>

				<!-- Search -->
				<div class="relative mb-4">
					<Search class="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
					<input
						type="text"
						class="input pl-10 w-full"
						placeholder="Search tables..."
						bind:value={searchTerm}
					/>
				</div>

				<!-- Tables -->
				<div class="space-y-1 max-h-96 overflow-y-auto">
					{#each filteredTables as table}
						<div class="border-b border-gray-100 dark:border-dark-800 last:border-0">
							<button
								class="w-full flex items-center justify-between p-2 hover:bg-gray-50 dark:hover:bg-dark-750 rounded transition-colors text-left"
								on:click={() => toggleTableExpansion(table.name)}
							>
								<div class="flex items-center gap-2">
									{#if expandedTables.has(table.name)}
										<ChevronDown class="h-4 w-4" />
									{:else}
										<ChevronRight class="h-4 w-4" />
									{/if}
									<Table2 class="h-4 w-4 text-gray-500" />
									<span class="text-sm font-medium">{table.name}</span>
								</div>
								<span class="text-xs text-gray-500">{table.count}</span>
							</button>
							
							{#if expandedTables.has(table.name)}
								<div class="pl-8 pb-2">
									{#if table.columns && table.columns.length > 0}
										<div class="space-y-1">
											{#each table.columns as column}
												<div class="flex items-center gap-2 text-xs">
													<span class="text-gray-700 dark:text-gray-300 font-mono">
														{column.name}
													</span>
													<span class="text-gray-500 dark:text-gray-500">
														{column.type}
													</span>
													{#if column.primary_key}
														<span class="px-1.5 py-0.5 rounded text-xs bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300">
															PK
														</span>
													{/if}
													{#if column.foreign_key}
														<span class="px-1.5 py-0.5 rounded text-xs bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
															FK
														</span>
													{/if}
													{#if !column.nullable}
														<span class="text-gray-400 text-xs">NOT NULL</span>
													{/if}
												</div>
											{/each}
										</div>
									{:else}
										<p class="text-xs text-gray-500 italic">No column details available</p>
									{/if}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>

			<!-- Sample Queries -->
			<div class="card p-4">
				<div class="flex items-center gap-2 mb-3">
					<FileText class="h-5 w-5 text-success-500" />
					<h2 class="text-sm font-semibold">Sample Queries</h2>
				</div>
				<div class="space-y-2">
					{#each sampleQueries as sample}
						<button
							class="w-full text-left p-2 rounded hover:bg-gray-50 dark:hover:bg-dark-750 transition-colors"
							on:click={() => loadSampleQuery(sample.query)}
						>
							<p class="text-xs font-medium text-gray-900 dark:text-gray-100">{sample.name}</p>
						</button>
					{/each}
				</div>
			</div>
		</div>

		<!-- Right Column: Query Editor & Results -->
		<div class="lg:col-span-2 space-y-4">
			<!-- Query Editor -->
			<div class="card p-4">
				<div class="flex items-center justify-between mb-3">
					<h2 class="text-lg font-semibold">SQL Query Editor</h2>
					<div class="flex items-center gap-2">
						<button
							class="btn-secondary flex items-center gap-2 text-sm"
							on:click={copyQuery}
							disabled={!sqlQuery}
						>
							{#if copied}
								<Check class="h-4 w-4" />
								Copied
							{:else}
								<Copy class="h-4 w-4" />
								Copy
							{/if}
						</button>
						<button
							class="btn-primary flex items-center gap-2"
							on:click={executeQuery}
							disabled={!sqlQuery || executing}
						>
							<Play class="h-4 w-4" />
							{executing ? 'Executing...' : 'Execute'}
						</button>
					</div>
				</div>

				<textarea
					class="w-full h-48 font-mono text-sm p-3 rounded-lg border border-gray-300 dark:border-dark-700 
					       bg-gray-50 dark:bg-dark-900 text-gray-900 dark:text-gray-100
					       focus:ring-2 focus:ring-primary-500 focus:border-transparent resize-none"
					placeholder="Enter your SQL query here...&#10;&#10;Example:&#10;SELECT * FROM headlines LIMIT 10;"
					bind:value={sqlQuery}
				/>

				<div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
					<p>⚠️ Note: Read-only queries only. No INSERT, UPDATE, or DELETE operations.</p>
				</div>
			</div>

			<!-- Query Results -->
			{#if queryError}
				<div class="card p-4 bg-warning-50 dark:bg-warning-900/20 border-warning-200 dark:border-warning-800">
					<div class="flex items-start gap-3">
						<AlertCircle class="h-5 w-5 text-warning-600 dark:text-warning-400 flex-shrink-0" />
						<div>
							<h3 class="font-semibold text-warning-900 dark:text-warning-200 mb-1">Query Error</h3>
							<p class="text-sm text-warning-800 dark:text-warning-300">{queryError}</p>
						</div>
					</div>
				</div>
			{/if}

			{#if queryResult}
				<div class="card p-4">
					<div class="flex items-center justify-between mb-3">
						<h2 class="text-lg font-semibold">Results ({queryResult.length} rows)</h2>
						<button
							class="btn-secondary flex items-center gap-2 text-sm"
							on:click={downloadResults}
						>
							<Download class="h-4 w-4" />
							Export CSV
						</button>
					</div>

					<div class="overflow-x-auto">
						<table class="min-w-full text-sm">
							<thead class="bg-gray-50 dark:bg-dark-850">
								<tr>
									{#each Object.keys(queryResult[0] || {}) as header}
										<th class="px-4 py-2 text-left font-semibold">{header}</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each queryResult as row}
									<tr class="border-b border-gray-100 dark:border-dark-800">
										{#each Object.values(row) as value}
											<td class="px-4 py-2">{value}</td>
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}

			<!-- Placeholder when no results -->
			{#if !queryResult && !queryError}
				<div class="card p-8 text-center">
					<Database class="h-12 w-12 text-gray-400 mx-auto mb-4" />
					<h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">
						Ready to Query
					</h3>
					<p class="text-gray-600 dark:text-gray-400 mb-4">
						Enter a SQL query above and click Execute to see results here.
					</p>
					<p class="text-sm text-gray-500 dark:text-gray-500">
						Try one of the sample queries to get started, or write your own!
					</p>
				</div>
			{/if}
		</div>
	</div>
</div>

