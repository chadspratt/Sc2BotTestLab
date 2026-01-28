import subprocess
import os
import glob
from datetime import datetime
from collections import defaultdict

from django.contrib import messages
from django.db.models import Max
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import reverse

from .models import Match

def match_list(request):
    """View to display match data grouped by test_group_id in a pivot table."""
    # Define difficulty order to match the filter dropdown
    difficulty_order = [
        'Easy', 'Medium', 'MediumHard', 'Hard', 'Harder', 'VeryHard',
        'CheatVision', 'CheatMoney', 'CheatInsane'
    ]
    
    # Get difficulty filter from request
    selected_difficulty = request.GET.get('difficulty', '')
    
    # Debug: Print the filter value and all GET parameters
    print(f"DEBUG: All GET parameters: {request.GET}")
    print(f"DEBUG: Selected difficulty filter: '{selected_difficulty}'")
    
    matches = Match.objects.using('sc2bot_test_lab_db_2').all().exclude(test_group_id=-1)
    
    # Debug: Print total matches before filtering
    print(f"DEBUG: Total matches before filtering: {matches.count()}")
    
    # Apply difficulty filter if selected
    if selected_difficulty:
        matches = matches.filter(opponent_difficulty=selected_difficulty)
        print(f"DEBUG: Matches after filtering by '{selected_difficulty}': {matches.count()}")
    
    # Group matches by test_group_id and create pivot structure
    grouped_matches = defaultdict(dict[str,Match])
    all_opponents = set()
    difficulty_groups = defaultdict(lambda: defaultdict(list))  # difficulty -> race -> builds
    
    # Track win/loss counts for each opponent
    opponent_stats = defaultdict(lambda: {'victories': 0, 'total_games': 0})
    replay_base_dir = r'C:\Users\inter\Documents\StarCraft II\Replays\Multiplayer\docker'
    
    for match in matches:
        opponent_name = f"{match.opponent_race}-{match.opponent_difficulty}-{match.opponent_build}"
        all_opponents.add(opponent_name)
        # Store both result and duration
        grouped_matches[match.test_group_id][opponent_name] = match
        if match.result in ['Victory', 'Defeat']:
            opponent_stats[opponent_name]['total_games'] += 1
            if match.result == 'Victory':
                opponent_stats[opponent_name]['victories'] += 1
        
        # Build hierarchical structure for headers
        difficulty_groups[match.opponent_difficulty][match.opponent_race].append(match.opponent_build)
    
    # Sort and deduplicate builds within each race/difficulty group
    for difficulty in difficulty_groups:
        for race in difficulty_groups[difficulty]:
            difficulty_groups[difficulty][race] = sorted(list(set(difficulty_groups[difficulty][race])))
    
    # Create ordered list of opponents for consistent column ordering
    sorted_opponents = []
    # Sort difficulties by the defined order instead of alphabetically
    sorted_difficulties = sorted(difficulty_groups.keys(), key=lambda x: difficulty_order.index(x) if x in difficulty_order else 999)
    
    # Build header structure and opponent order
    header_structure = []
    for difficulty in sorted_difficulties:
        races = sorted(difficulty_groups[difficulty].keys())
        difficulty_span = sum(len(difficulty_groups[difficulty][race]) for race in races)
        
        race_headers = []
        for race in races:
            builds = difficulty_groups[difficulty][race]
            for build in builds:
                opponent_name = f"{race}-{difficulty}-{build}"
                sorted_opponents.append(opponent_name)
            
            race_headers.append({
                'name': race,
                'span': len(builds),
                'builds': builds
            })
        
        header_structure.append({
            'difficulty': difficulty,
            'span': difficulty_span,
            'races': race_headers
        })
    
    # Sort test groups for consistent display
    sorted_groups = sorted(grouped_matches.keys(), reverse=True)
    
    # Create the pivot table data
    max_group_id = max(sorted_groups) if sorted_groups else -1
    pivot_data = []
    for group_id in sorted_groups:
        row = {'test_group_id': group_id, 'results': []}
        
        # Calculate win percentage and average duration for this group
        group_victories = 0
        group_total_games = 0
        group_total_duration = 0
        group_games_with_duration = 0
        
        for opponent in sorted_opponents:
            match_data = grouped_matches[group_id].get(opponent, None)
            if not match_data:
                row['results'].append(None)
                continue
                
            if group_id != max_group_id and match_data.result == 'Pending':
                match_data.result = 'Aborted'

            row['results'].append(match_data)
            
            # Count wins/losses for group percentage
            result = match_data.result
            duration = match_data.duration_in_game_time
            
            if result in ['Victory', 'Defeat']:
                group_total_games += 1
                if result == 'Victory':
                    group_victories += 1
        
            # Sum durations for average calculation
            if duration is not None and duration > 0:
                group_total_duration += duration
                group_games_with_duration += 1
        
        # Calculate group win percentage
        if group_total_games > 0:
            group_win_percentage = (group_victories / group_total_games) * 100
            row['group_win_percentage'] = f"{group_win_percentage:.1f}%"
        else:
            row['group_win_percentage'] = "-"
        
        # Calculate average game length
        if group_games_with_duration > 0:
            avg_duration = group_total_duration / group_games_with_duration
            row['avg_duration'] = int(avg_duration)
        else:
            row['avg_duration'] = None
        
        pivot_data.append(row)
    
    # Calculate win percentages for each opponent column
    win_percentages = []
    for opponent in sorted_opponents:
        stats = opponent_stats[opponent]
        if stats['total_games'] > 0:
            win_percentage = (stats['victories'] / stats['total_games']) * 100
            win_percentages.append(f"{win_percentage:.1f}%")
        else:
            win_percentages.append("-")

    # Calculate win rates by race within each difficulty
    for difficulty_group in header_structure:
        difficulty_name = difficulty_group['difficulty']
        for race_group in difficulty_group['races']:
            race_name = race_group['name']
            race_victories = 0
            race_total_games = 0
            
            # Count wins/losses for this specific race-difficulty combination
            for opponent in sorted_opponents:
                if opponent.startswith(f"{race_name}-{difficulty_name}-"):
                    stats = opponent_stats[opponent]
                    race_total_games += stats['total_games']
                    race_victories += stats['victories']
            
            if race_total_games > 0:
                race_win_percentage = (race_victories / race_total_games) * 100
                race_group['win_rate'] = f"{race_win_percentage:.0f}%"
            else:
                race_group['win_rate'] = "-"
            
            # Add win rates to individual builds
            for i, build in enumerate(race_group['builds']):
                opponent_name = f"{race_name}-{difficulty_name}-{build}"
                stats = opponent_stats[opponent_name]
                if stats['total_games'] > 0:
                    build_win_percentage = (stats['victories'] / stats['total_games']) * 100
                    race_group['builds'][i] = f"{build} {build_win_percentage:.0f}%"
                else:
                    race_group['builds'][i] = f"{build} -"

    # Calculate win rates by difficulty
    difficulty_win_rates = {}
    for difficulty in sorted_difficulties:
        difficulty_victories = 0
        difficulty_total_games = 0
        for opponent in sorted_opponents:
            if f"-{difficulty}-" in opponent:
                stats = opponent_stats[opponent]
                difficulty_total_games += stats['total_games']
                difficulty_victories += stats['victories']
        
        if difficulty_total_games > 0:
            difficulty_win_percentage = (difficulty_victories / difficulty_total_games) * 100
            difficulty_win_rates[difficulty] = f"{difficulty_win_percentage:.0f}%"
        else:
            difficulty_win_rates[difficulty] = "-"

    # Add difficulty win rates to header structure
    for difficulty_group in header_structure:
        difficulty_group['win_rate'] = difficulty_win_rates.get(difficulty_group['difficulty'], "-")

    return render(request, 'test_lab/match_list.html', {
        'pivot_data': pivot_data,
        'opponents': sorted_opponents,
        'header_structure': header_structure,
        'selected_difficulty': selected_difficulty
    })

def get_next_test_group_id() -> int:
    """Get the next test group ID by incrementing the highest completed test group ID."""
    result = Match.objects.using('sc2bot_test_lab_db_2').filter(
        end_timestamp__isnull=False
    ).aggregate(Max('test_group_id'))['test_group_id__max']
    
    # If no completed matches exist, start at 0, otherwise increment by 1
    return 0 if result is None else result + 1

def create_pending_match(test_group_id: int, race: str, build: str, difficulty: str) -> int:
    """Create a pending match entry and return the match ID."""
    match = Match(
        test_group_id=test_group_id,
        start_timestamp=datetime.now(),
        map_name="TBD",  # Map will be determined by run_bottato_vs_computer.py
        opponent_race=race.capitalize(),
        opponent_difficulty=difficulty or "CheatInsane",
        opponent_build=build.capitalize(),
        result="Pending"
    )
    match.save(using='sc2bot_test_lab_db_2')
    assert isinstance(match.id, int)
    return match.id

def trigger_tests(request):
    """Trigger the test suite by starting Docker containers directly."""
    if request.method == 'POST':
        try:
            docker_compose_path = r'c:\Users\inter\Documents\sc_bot\bot'
            logs_dir = r'C:\Users\inter\Documents\StarCraft II\Replays\Multiplayer\docker'
            
            # Create logs directory if it doesn't exist
            os.makedirs(logs_dir, exist_ok=True)
            
            # Check if docker-compose.yml exists
            compose_file = os.path.join(docker_compose_path, 'docker-compose.yml')
            if not os.path.exists(compose_file):
                messages.error(request, f'docker-compose.yml not found at: {compose_file}')
                return redirect('match_list')
            
            # Get difficulty filter from the current page state
            difficulty = request.POST.get('difficulty', '')
            
            # Get next test group ID
            test_group_id = get_next_test_group_id()
            
            # Clean up containers first
            cleanup_command = ['docker', 'container', 'prune', '-f']
            subprocess.run(cleanup_command, cwd=docker_compose_path)
            
            # Start all test jobs
            processes = []
            for race in ('protoss', 'terran', 'zerg'):
                for build in ['rush', 'timing', 'macro', 'power', 'air']:
                    # Create pending match entry and get match ID
                    match_id = create_pending_match(test_group_id, race, build, difficulty)
                    
                    # Create log file path
                    log_file = os.path.join(logs_dir, f"{match_id}_{race}_{build}.log")
                    
                    # Build Docker compose command with environment variables
                    command = ['docker', 'compose', 'run', '--rm', 
                              '-e', f'RACE={race}', 
                              '-e', f'BUILD={build}',
                              '-e', f'MATCH_ID={match_id}']
                    
                    if difficulty:
                        command.extend(['-e', f'DIFFICULTY={difficulty}'])
                    
                    command.append('bot')
                    
                    # Start the process with output redirected to log file
                    with open(log_file, 'w') as log:
                        process = subprocess.Popen(command, cwd=docker_compose_path, stdout=log, stderr=log)
                    processes.append((process, f"{race}_{build}"))
            
            difficulty_msg = f" with difficulty {difficulty}" if difficulty else ""
            messages.success(request, f'Test suite started successfully{difficulty_msg}! {len(processes)} tests running. Logs in: {logs_dir}')
            
        except Exception as e:
            messages.error(request, f'Failed to start test suite: {str(e)}')
    
    # Preserve the difficulty filter in the redirect
    difficulty = request.POST.get('difficulty', '')
    if difficulty:
        return redirect(f"{reverse('match_list')}?difficulty={difficulty}")
    else:
        return redirect('match_list')

def serve_replay(request, match_id):
    """Open replay files with StarCraft 2 locally."""
    replay_dir = r'C:\Users\inter\Documents\StarCraft II\Replays\Multiplayer\docker'
    
    # Find replay file matching the match_id pattern
    replay_pattern = os.path.join(replay_dir, f"{match_id}_*.SC2Replay")
    replay_files = glob.glob(replay_pattern)
    
    if not replay_files:
        raise Http404("Replay file not found")
    
    file_path = replay_files[0]  # Take the first matching file

    subprocess.Popen([r"C:\Program Files (x86)\StarCraft II\Support\SC2Switcher.exe", file_path])
    from django.http import HttpResponse
    return HttpResponse(status=204)

def serve_log(request, match_id):
    """Serve log file for viewing."""
    from django.http import FileResponse
    replay_dir = r'C:\Users\inter\Documents\StarCraft II\Replays\Multiplayer\docker'
    
    # Find log file matching the match_id pattern
    log_pattern = os.path.join(replay_dir, f"{match_id}*.log")
    log_files = glob.glob(log_pattern)
    
    if not log_files:
        raise Http404("Log file not found")
    
    file_path = log_files[0]  # Take the first matching file
    
    return FileResponse(open(file_path, 'rb'), content_type='text/plain')

def map_breakdown(request):
    """View to display match data grouped by map in a pivot table."""
    # Define difficulty order to match the filter dropdown
    difficulty_order = [
        'Easy', 'Medium', 'MediumHard', 'Hard', 'Harder', 'VeryHard',
        'CheatVision', 'CheatMoney', 'CheatInsane'
    ]
    
    # Get difficulty filter from request
    selected_difficulty = request.GET.get('difficulty', '')
    
    matches = Match.objects.using('sc2bot_test_lab_db_2').all().exclude(test_group_id=-1)
    
    # Apply difficulty filter if selected
    if selected_difficulty:
        matches = matches.filter(opponent_difficulty=selected_difficulty)
    
    # Group matches by map and create pivot structure
    grouped_matches = defaultdict(lambda: defaultdict(list))  # map -> opponent -> [matches]
    all_opponents = set()
    difficulty_groups = defaultdict(lambda: defaultdict(list))  # difficulty -> race -> builds
    
    # Track win/loss counts for each map/opponent combination
    map_opponent_stats = defaultdict(lambda: {'victories': 0, 'total_games': 0, 'total_duration': 0, 'games_with_duration': 0})
    
    for match in matches:
        opponent_name = f"{match.opponent_race}-{match.opponent_difficulty}-{match.opponent_build}"
        all_opponents.add(opponent_name)
        
        # Group by map
        grouped_matches[match.map_name][opponent_name].append(match)
        
        # Track stats for this map/opponent combination
        key = (match.map_name, opponent_name)
        if match.result in ['Victory', 'Defeat']:
            map_opponent_stats[key]['total_games'] += 1
            if match.result == 'Victory':
                map_opponent_stats[key]['victories'] += 1
        
        if match.duration_in_game_time is not None and match.duration_in_game_time > 0:
            map_opponent_stats[key]['total_duration'] += match.duration_in_game_time
            map_opponent_stats[key]['games_with_duration'] += 1
        
        # Build hierarchical structure for headers
        difficulty_groups[match.opponent_difficulty][match.opponent_race].append(match.opponent_build)
    
    # Sort and deduplicate builds within each race/difficulty group
    for difficulty in difficulty_groups:
        for race in difficulty_groups[difficulty]:
            difficulty_groups[difficulty][race] = sorted(list(set(difficulty_groups[difficulty][race])))
    
    # Create ordered list of opponents for consistent column ordering
    sorted_opponents = []
    sorted_difficulties = sorted(difficulty_groups.keys(), key=lambda x: difficulty_order.index(x) if x in difficulty_order else 999)
    
    # Build header structure and opponent order
    header_structure = []
    for difficulty in sorted_difficulties:
        races = sorted(difficulty_groups[difficulty].keys())
        difficulty_span = sum(len(difficulty_groups[difficulty][race]) for race in races)
        
        race_headers = []
        for race in races:
            builds = difficulty_groups[difficulty][race]
            for build in builds:
                opponent_name = f"{race}-{difficulty}-{build}"
                sorted_opponents.append(opponent_name)
            
            race_headers.append({
                'name': race,
                'span': len(builds),
                'builds': builds
            })
        
        header_structure.append({
            'difficulty': difficulty,
            'span': difficulty_span,
            'races': race_headers
        })
    
    # Sort maps alphabetically
    sorted_maps = sorted(grouped_matches.keys())
    
    # Create the pivot table data
    pivot_data = []
    for map_name in sorted_maps:
        row = {'map_name': map_name, 'results': [], 'overall_win_rate': None, 'overall_avg_duration': None, 'overall_wins': 0, 'overall_games': 0}
        map_total_victories = 0
        map_total_games = 0
        map_total_duration = 0
        map_games_with_duration = 0
        for opponent in sorted_opponents:
            key = (map_name, opponent)
            stats = map_opponent_stats[key]
            
            # Calculate win percentage for this map/opponent combo
            if stats['total_games'] > 0:
                win_percentage = (stats['victories'] / stats['total_games']) * 100
                win_rate_str = f"{win_percentage:.0f}%"
            else:
                win_rate_str = None
            
            # Calculate average duration for this map/opponent combo
            if stats['games_with_duration'] > 0:
                avg_duration = int(stats['total_duration'] / stats['games_with_duration'])
            else:
                avg_duration = None
            
            cell_data = {
                'win_rate': win_rate_str,
                'avg_duration': avg_duration,
                'wins': stats['victories'],
                'games_played': stats['total_games']
            }
            
            row['results'].append(cell_data)
            map_total_victories += stats['victories']
            map_total_games += stats['total_games']
            map_total_duration += stats['total_duration']
            map_games_with_duration += stats['games_with_duration']
        
        if map_total_games > 0:
            overall_win_percentage = (map_total_victories / map_total_games) * 100
            row['overall_win_rate'] = f"{overall_win_percentage:.0f}%"
            row['overall_wins'] = map_total_victories
            row['overall_games'] = map_total_games
        else:
            row['overall_win_rate'] = None
            row['overall_wins'] = 0
            row['overall_games'] = 0
        
        if map_games_with_duration > 0:
            row['overall_avg_duration'] = int(map_total_duration / map_games_with_duration)
        else:
            row['overall_avg_duration'] = None

        pivot_data.append(row)
    
    # Calculate win rates for header structure (same as match_list)
    opponent_stats = defaultdict(lambda: {'victories': 0, 'total_games': 0})
    for opponent in sorted_opponents:
        for map_name in sorted_maps:
            key = (map_name, opponent)
            stats = map_opponent_stats[key]
            opponent_stats[opponent]['total_games'] += stats['total_games']
            opponent_stats[opponent]['victories'] += stats['victories']
    
    # Calculate win rates by race within each difficulty
    for difficulty_group in header_structure:
        difficulty_name = difficulty_group['difficulty']
        for race_group in difficulty_group['races']:
            race_name = race_group['name']
            race_victories = 0
            race_total_games = 0
            
            for opponent in sorted_opponents:
                if opponent.startswith(f"{race_name}-{difficulty_name}-"):
                    stats = opponent_stats[opponent]
                    race_total_games += stats['total_games']
                    race_victories += stats['victories']
            
            if race_total_games > 0:
                race_win_percentage = (race_victories / race_total_games) * 100
                race_group['win_rate'] = f"{race_win_percentage:.0f}%"
            else:
                race_group['win_rate'] = "-"
            
            # Add win rates to individual builds
            for i, build in enumerate(race_group['builds']):
                opponent_name = f"{race_name}-{difficulty_name}-{build}"
                stats = opponent_stats[opponent_name]
                if stats['total_games'] > 0:
                    build_win_percentage = (stats['victories'] / stats['total_games']) * 100
                    race_group['builds'][i] = f"{build} {build_win_percentage:.0f}%"
                else:
                    race_group['builds'][i] = f"{build} -"
    
    # Calculate win rates by difficulty
    difficulty_win_rates = {}
    for difficulty in sorted_difficulties:
        difficulty_victories = 0
        difficulty_total_games = 0
        for opponent in sorted_opponents:
            if f"-{difficulty}-" in opponent:
                stats = opponent_stats[opponent]
                difficulty_total_games += stats['total_games']
                difficulty_victories += stats['victories']
        
        if difficulty_total_games > 0:
            difficulty_win_percentage = (difficulty_victories / difficulty_total_games) * 100
            difficulty_win_rates[difficulty] = f"{difficulty_win_percentage:.0f}%"
        else:
            difficulty_win_rates[difficulty] = "-"
    
    # Add difficulty win rates to header structure
    for difficulty_group in header_structure:
        difficulty_group['win_rate'] = difficulty_win_rates.get(difficulty_group['difficulty'], "-")
    
    return render(request, 'test_lab/map_breakdown.html', {
        'pivot_data': pivot_data,
        'opponents': sorted_opponents,
        'header_structure': header_structure,
        'selected_difficulty': selected_difficulty
    })
