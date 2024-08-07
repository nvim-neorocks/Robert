import argparse
import json

import pandas as pd
from rich.console import Console
from rich.table import Table


class DatabaseAnalyzer:

    def __init__(self, database_path='database.json', lengthA=10, lengthB=10):
        self.database_path = database_path
        self.lengthA = lengthA
        self.lengthB = lengthB
        self.plugins_df = None
        self.console = Console()
        self.load_database()

    def load_database(self):
        with open(self.database_path, 'r') as file:
            data = json.load(file)
        self.plugins_df = pd.DataFrame.from_dict(data, orient='index')
        self.plugins_df['activity_score'] = (
            self.plugins_df['forks_count'] +
            self.plugins_df['stargazers_count'] -
            self.plugins_df['open_issues_count'])
        self.simplify_language_distribution()

    def simplify_language_distribution(self):
        # Ensure all None values are replaced with 'Unknown' or another placeholder
        # This step ensures that there will be no KeyError when accessing language_counts
        self.plugins_df['language'] = self.plugins_df['language'].fillna(
            'Unknown')

        # Recalculate language counts after filling None values
        language_counts = self.plugins_df['language'].value_counts()

        # Use get to safely access the count for each language, defaulting to 0 if not found
        # This approach avoids KeyError for languages not present in language_counts
        self.plugins_df['simplified_language'] = self.plugins_df[
            'language'].apply(lambda x: x
                              if language_counts.get(x, 0) > 1 else 'Other')

    def calculate_statistics(self):
        stats_df = self.plugins_df[[
            'forks_count', 'stargazers_count', 'open_issues_count',
            'activity_score'
        ]].agg(['mean', 'std']).transpose()
        return stats_df

    def get_language_distribution(self):
        return self.plugins_df['simplified_language'].value_counts()

    def get_average_activity_score_by_language(self):
        # Calculate average activity score by language
        return self.plugins_df.groupby(
            'simplified_language')['activity_score'].mean().sort_values(
                ascending=False)

    def get_topics_distribution(self):
        topics_series = self.plugins_df['topics'].explode().value_counts()
        return topics_series.head(self.lengthB)  # Only the top 5 topics

    def print_summary(self):
        topics_distribution = self.get_topics_distribution()
        self.console.print("\nTop Topics distribution:",
                           style="bold underline")
        self.print_table(topics_distribution, ['Topic', 'Count'])

    def print_table(self, data, columns):
        table = Table(show_header=True, header_style="bold magenta")
        for column in columns:
            table.add_column(column, style="dim")
        if isinstance(data, pd.Series):
            for index, value in data.items():
                table.add_row(str(index), str(value))
        else:
            for index, row in data.iterrows():
                table.add_row(index, f"{row['mean']:.2f}", f"{row['std']:.2f}")
        self.console.print(table)

    def print_top_plugins(self):
        # Define the categories and their corresponding column names in the DataFrame
        categories = {
            "Stars": "stargazers_count",
            "Issues": "open_issues_count",
            "Forks": "forks_count"
        }

        for category, column_name in categories.items():
            self.console.print(f"\nTop {self.lengthA} Plugins by {category}:",
                               style="bold underline magenta")
            top_plugins = self.plugins_df.nlargest(self.lengthA,
                                                   column_name)[[column_name]]

            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Plugin", style="dim", justify="left")
            table.add_column(category, style="dim", justify="right")

            for plugin_name, row in top_plugins.iterrows():
                table.add_row(plugin_name, str(row[column_name]))

            self.console.print(table)

        total_plugins = len(self.plugins_df)
        lua_plugins = len(
            self.plugins_df[self.plugins_df['language'] == 'Lua'])
        proportion_lua = (lua_plugins / total_plugins) * 100
        average_activity_score = self.plugins_df['activity_score'].mean()

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Total Plugins", style="dim", justify="right")
        table.add_column("Lua Plugins", style="dim", justify="right")
        table.add_column("Proportion of Lua Plugins (%)",
                         style="dim",
                         justify="right")
        table.add_column("Average Activity Score",
                         style="dim",
                         justify="right")

        table.add_row(str(total_plugins), str(lua_plugins),
                      f"{proportion_lua:.2f}", f"{average_activity_score:.2f}")

        self.console.print(table)

    def generate_markdown_table(self, data, columns):
        markdown_table = "| " + " | ".join(columns) + " |\n"
        markdown_table += "| " + " | ".join(['---'] * len(columns)) + " |\n"
        if isinstance(data, pd.Series):
            for index, value in data.items():
                markdown_table += "| " + " | ".join([str(index),
                                                     str(value)]) + " |\n"
        else:
            for index, row in data.iterrows():
                markdown_table += "| " + index + " | " + f"{row['mean']:.2f}" + " | " + f"{row['std']:.2f}" + " |\n"
        return markdown_table

    def save_to_markdown(self):
        new_content = ""
        categories = {
            "Stars": "stargazers_count",
            "Issues": "open_issues_count",
            "Forks": "forks_count"
        }

        # Generate HTML for the top plugins in each category
        plugins_html = self.generate_html_for_plugins(categories)
        new_content += "<div style='display:flex;flex-direction:row;justify-content:space-between;'>" + plugins_html + "</div>\n\n"

        # Final stats in Markdown
        total_plugins = len(self.plugins_df)
        lua_plugins = len(
            self.plugins_df[self.plugins_df['language'] == 'Lua'])
        proportion_lua = (lua_plugins / total_plugins) * 100
        average_activity_score = self.plugins_df['activity_score'].mean()
        new_content += "### Final Stats\n"
        new_content += f"- Total Plugins: {total_plugins}\n"
        new_content += f"- Lua Plugins: {lua_plugins}\n"
        new_content += f"- Proportion of Lua Plugins (%): {proportion_lua:.2f}\n"
        new_content += f"- Average Activity Score: {average_activity_score:.2f}\n"

        # Read and split the existing README
        try:
            with open("README.md", "r+") as md_file:
                content = md_file.read()
                parts = content.split("# Database Information", 1)
                updated_content = parts[
                    0] + "# Database Information\n\n" + new_content
                md_file.seek(0)
                md_file.write(updated_content)
                md_file.truncate()
        except FileNotFoundError:
            with open("README.md", "w") as md_file:
                md_file.write("# Database Information\n\n" + new_content)

    def generate_html_for_plugins(self, categories):
        html_content = '<table><tr>'
        for category, column_name in categories.items():
            top_plugins = self.plugins_df.nlargest(self.lengthA,
                                                   column_name)[[column_name]]
            html_content += '<td><h3>Top 10 Plugins by ' + category + '</h3>'
            html_content += '<table border="1"><tr><th>Plugin</th><th>' + category + '</th></tr>'
            for plugin_name, row in top_plugins.iterrows():
                html_content += '<tr><td>' + plugin_name + '</td><td>' + str(
                    row[column_name]) + '</td></tr>'
            html_content += '</table></td>'
        html_content += '</tr></table>'
        return html_content


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Check the database')
    parser.add_argument('--db',
                        help='Path to the database file',
                        default='database.json',
                        type=str)
    parser.add_argument("--lenA",
                        help="Length of items you want to view",
                        default=10,
                        type=int)
    parser.add_argument("--lenB",
                        help="Length of Topic Distribution you want to view",
                        default=10,
                        type=int)

    args = parser.parse_args()
    analyzer = DatabaseAnalyzer(database_path=args.db,
                                lengthA=args.lenA,
                                lengthB=args.lenB)
    # analyzer.print_summary()
    # analyzer.print_top_plugins()
    analyzer.save_to_markdown()
