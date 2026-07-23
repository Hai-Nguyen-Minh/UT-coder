import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

def generate_report(results_csv="core/benchmark/benchmark_results.csv", output_dir="core/benchmark"):
    if not os.path.exists(results_csv):
        print(f"Results file not found: {results_csv}")
        return
        
    df = pd.read_csv(results_csv)
    
    if df.empty:
        print("No data in results file.")
        return
        
    # Create output dir if needed
    os.makedirs(output_dir, exist_ok=True)
    
    # Preprocess boolean to numeric for aggregation
    df['Pass_at_1'] = df['Pass_at_1'].astype(bool).astype(int) * 100
    df['Pass_at_3'] = df['Pass_at_3'].astype(bool).astype(int) * 100
    
    # Group by model
    summary = df.groupby('Model').agg({
        'Pass_at_1': 'mean',
        'Pass_at_3': 'mean',
        'Coverage': 'mean',
        'Attempts': 'mean',
        'TimeTaken_s': 'mean'
    }).reset_index()
    
    print("\n--- Benchmark Summary ---")
    print(summary.to_string(index=False))
    
    # Apply Academic / LaTeX friendly styling
    plt.rcParams.update({
        'font.family': 'serif',
        'font.serif': ['Times New Roman', 'Computer Modern Roman', 'serif'],
        'font.size': 12,
        'axes.labelsize': 14,
        'axes.titlesize': 14,
        'xtick.labelsize': 12,
        'ytick.labelsize': 12,
        'legend.fontsize': 12,
        'figure.dpi': 300,
        'savefig.dpi': 300,
        'savefig.bbox': 'tight'
    })
    sns.set_theme(style="ticks", rc={"axes.grid": True, "grid.linestyle": "--", "grid.alpha": 0.6})
    palette = sns.color_palette("Greys", 3)
    
    def add_hatches(ax):
        hatches = ['//', '\\\\', 'xx', '--', '||']
        for i, bar in enumerate(ax.patches):
            hatch = hatches[(i // len(summary)) % len(hatches)]
            bar.set_hatch(hatch)
            bar.set_edgecolor('black')

    # 1. Plot Pass Rates
    plt.figure(figsize=(8, 5))
    pass_data = summary[['Model', 'Pass_at_1', 'Pass_at_3']].melt(id_vars='Model', var_name='Metric', value_name='Pass Rate (%)')
    ax1 = sns.barplot(x='Model', y='Pass Rate (%)', hue='Metric', data=pass_data, palette=['#D3D3D3', '#808080'], edgecolor='black')
    add_hatches(ax1)
    plt.title('Zero-shot vs Reflection Pass Rate', fontweight='bold')
    plt.ylim(0, 100)
    plt.legend(title='')
    sns.despine()
    plt.savefig(os.path.join(output_dir, 'pass_rates.pdf'))
    plt.savefig(os.path.join(output_dir, 'pass_rates.png'))
    plt.close()
    
    # 2. Plot Coverage
    plt.figure(figsize=(8, 5))
    cov_data = summary[['Model', 'Coverage']].melt(id_vars='Model', var_name='Metric', value_name='Score (%)')
    ax2 = sns.barplot(x='Model', y='Score (%)', hue='Metric', data=cov_data, palette=['#A9A9A9'], edgecolor='black')
    add_hatches(ax2)
    plt.title('Code Coverage', fontweight='bold')
    plt.ylim(0, 100)
    plt.legend(title='')
    sns.despine()
    plt.savefig(os.path.join(output_dir, 'coverage.pdf'))
    plt.savefig(os.path.join(output_dir, 'coverage.png'))
    plt.close()
    
    # 3. Plot Time Taken
    plt.figure(figsize=(8, 5))
    ax3 = sns.barplot(x='Model', y='TimeTaken_s', hue='Model', data=summary, palette='Greys', edgecolor='black', legend=False)
    for i, bar in enumerate(ax3.patches):
        bar.set_hatch('//')
    plt.title('Average Inference Latency', fontweight='bold')
    plt.ylabel('Time (Seconds)')
    sns.despine()
    plt.savefig(os.path.join(output_dir, 'time_taken.pdf'))
    plt.savefig(os.path.join(output_dir, 'time_taken.png'))
    plt.close()
    
    print(f"\nAcademic Charts (PDF & PNG) saved to {output_dir}")

if __name__ == "__main__":
    generate_report()
