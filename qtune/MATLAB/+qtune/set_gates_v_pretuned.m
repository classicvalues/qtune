function [ actual_point ] = set_gates_v_pretuned( new_point )
%setting the real gates to new values and read them out to correct numeric
%inaccuracy
%   Detailed explanation goes here
global tunedata
global pretuned_point
global smdata
gatechannels=tunedata.gatechan;

% disp(pretuned_point(1:6)'-new_point);
% 'The gates are changed by the values above away from the pretuned point to the absolute value below!'
% new_point

for i=1:6
	if abs(pretuned_point(i)-new_point(i)) > 5e-3
		for i = 1:8
			smset(gatechannels(i),pretuned_point(i))
		end
		error('emergency: the dot is 5mV away from pretuned point!!!!')
	end
end

% str = input('The program wants to set the gates to the values above! [Y/N]','s')
% if strcmp(str,'Y')
    for i=1:6
        smset(gatechannels(i),new_point(i));
    end
% end
actual_point=cell2mat(smget({smdata.channels(tunedata.gatechan).name})); 
actual_point=actual_point(1:6)';
end

