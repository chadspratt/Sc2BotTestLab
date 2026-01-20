import subprocess
import os

from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse
from .models import Match
from collections import defaultdict

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
    
    matches = Match.objects.using('sc2bot_test_lab_db').all().exclude(test_group_id=-1)
    
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

    return render(request, 'test_lab/match_list.html', {
        'pivot_data': pivot_data,
        'opponents': sorted_opponents,
        'header_structure': header_structure,
        'selected_difficulty': selected_difficulty,
        'win_percentages': win_percentages
    })

def trigger_tests(request):
    """Trigger the PowerShell test suite."""
    if request.method == 'POST':
        try:
            script_path = r'c:\Users\inter\Documents\sc_bot\bot\test_all_opponents.ps1'
            
            # Check if script exists
            if not os.path.exists(script_path):
                messages.error(request, f'Test script not found at: {script_path}')
                return redirect('match_list')
            
            # Get difficulty filter from the current page state
            difficulty = request.POST.get('difficulty', '')
            
            # Build command arguments
            command = [
                'powershell.exe', 
                '-ExecutionPolicy', 'Bypass',
                '-File', script_path
            ]
            
            # Add difficulty parameter if specified
            if difficulty:
                command.extend(['-Difficulty', difficulty])
            
            # Run PowerShell script in the background
            subprocess.Popen(command, cwd=r'c:\Users\inter\Documents\sc_bot\bot')
            
            difficulty_msg = f" with difficulty {difficulty}" if difficulty else ""
            messages.success(request, f'Test suite started successfully{difficulty_msg}! Check the match results page for updates.')
            
        except Exception as e:
            messages.error(request, f'Failed to start test suite: {str(e)}')
    
    # Preserve the difficulty filter in the redirect
    difficulty = request.POST.get('difficulty', '')
    if difficulty:
        return redirect(f"{reverse('match_list')}?difficulty={difficulty}")
    else:
        return redirect('match_list')
