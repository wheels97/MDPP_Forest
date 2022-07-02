"""
This project is adapted from https://github.com/edgeslab/CTL

by Sizhe Yu 
2022
"""

from sklearn.model_selection import train_test_split

from .ct_util_MT_testNl_Weigh import *
import numpy as np
import time


# Class that defines the causal tree nodes
class CausalTree:
    def __init__(self, cont=False, max_depth=-1, min_size=2, weight=0.5, seed=None, split_size=0.5, honest=False,
                 val_honest=False, variables=None, weight_obj=False, base_obj=True, quartile=False, verbose=False,
                 max_values=None, quantile=True, tnums=30, weight_pick=True):
        self.root = None
        self.max = -np.inf
        self.min = np.inf
        self.num_leaves = 0
        self.max_depth = max_depth
        self.min_size = min_size
        self.weight = weight
        self.seed = seed
        self.cont = cont
        if cont:
            self.eval_func = self.objective_cont
        else:
            self.eval_func = self.objective
        self.quartile = quartile#select the quartile for trigger
        self.quantile = quantile#quantile sketch for the features

        self.weight_obj = weight_obj
        self.base_obj = base_obj

        self.honest = honest
        self.val_honest = val_honest

        self.split_size = split_size
        self.obj = 0.0
        self.tree_depth = 0
        self.variables = variables
        self.verbose = verbose
        self.start = 0.0
        self.time = 0.0
        self.max_values = max_values #the range of X while splitting
        self.mse = 0.0
        self.tnums = tnums
        self.weight_pick = weight_pick

    class Node:
        def __init__(self, col=-1, value=None, true_branch=None, false_branch=None, effect=0.0,
                     treat_split=None, leaf=False, leaf_num=None, current_obj=0.0, p_val=-1, samples=0, node_var=0.0,
                     node_depth=0, node_mse=0.0):
            self.col = col  # the column of the feature used for splitting
            self.value = value  # the value that splits the data

            self.current_obj = current_obj
            self.effect = effect
            self.p_val = p_val
            self.treat_split = treat_split  # treatment splitting location (for continuous values)
            self.variance = node_var

            self.true_branch = true_branch  # pointer to node for true branch
            self.false_branch = false_branch  # pointer to node for false branch
            self.leaf = leaf  # true/false if leaf or not
            self.leaf_num = leaf_num  # the leaf label

            self.samples = samples

            self.feature_name = None
            self.feature_split = None

            self.node_depth = node_depth
            self.node_mse = node_mse

    def fit(self, rows, labels, treatment):
        if rows.shape[0] == 0:
            return self.Node()

        if self.seed is not None:
            np.random.seed(self.seed)

        if self.verbose:
            self.start = time.time()

        curr_split = None
        current_var = 0.0
        #处理binary t
        if self.eval_func == self.objective:
            if self.val_honest or self.honest:
                if self.val_honest:
                    train_rows, est_rows, train_outcome, est_labels, train_treat, est_treatment = \
                        train_test_split(rows, labels, treatment, shuffle=True, test_size=self.split_size)
                else:
                    train_rows, est_rows, train_outcome, est_labels, train_treat, est_treatment = \
                        train_test_split(rows, labels, treatment, shuffle=True, test_size=0.5)

                _, effect = tau_squared(est_labels, est_treatment)#return ACE
                p_val = get_pval(est_labels, est_treatment)#return p_value

                train_to_est_ratio = est_rows.shape[0] / train_rows.shape[0]
                current_var_treat, current_var_control = variance(train_outcome, train_treat)
                num_cont, num_treat = get_num_treat(train_treat)[1:]
                current_var = (1 + train_to_est_ratio) * (
                        (current_var_treat / num_treat) + (current_var_control / num_cont))#Honest item
            else:
                _, effect = tau_squared(labels, treatment)
                p_val = get_pval(labels, treatment)

        elif self.eval_func == self.objective_cont:
        #deal with continues t，output trigger、effect、p_value、temp F of the leaf 
            if self.val_honest or self.honest:
                if self.val_honest:
                    train_rows, est_rows, train_outcome, est_labels, train_treat, est_treatment = \
                        train_test_split(rows, labels, treatment, shuffle=True, test_size=self.split_size)
                else:
                    train_rows, est_rows, train_outcome, est_labels, train_treat, est_treatment = \
                        train_test_split(rows, labels, treatment, shuffle=True, test_size=0.5)

                _, effect, curr_split = tau_squared_cont(train_outcome, train_treat, self.min_size, self.quartile,tnums=self.tnums)
    
                # p_val = get_pval(est_labels, est_treatment, treat_split=curr_split)

                train_to_est_ratio = est_rows.shape[0] / train_rows.shape[0]
                current_var_treat, current_var_control = variance(train_outcome, train_treat)
                num_cont, num_treat = get_num_treat(train_treat, self.min_size)[1:]
                current_var = (1 + train_to_est_ratio) * (
                        (current_var_treat / num_treat) + (current_var_control / num_cont))
            #calculation variance is not supported currently, so honest item cannot be used
            else:
                effect, curr_split = tau_squared_cont(labels, treatment, self.min_size, self.quartile,tnums=self.tnums)
                # p_val = get_pval(labels, treatment, curr_split)
        else:
            # otherwise something is wrong, assume binary learn
            _, effect = tau_squared(labels, treatment)
            # p_val = get_pval(labels, treatment)

        if self.seed is not None:
            np.random.seed(self.seed)

        if self.honest:
            rows, est_rows, labels, est_labels, treatment, est_treatment = \
                train_test_split(rows, labels, treatment, shuffle=True, test_size=0.5)
            self.root = self.Node(col=-1, value=None, current_obj=0.0, effect=effect,
                                  p_val=p_val, treat_split=curr_split, node_var=current_var, node_depth=0)
            self.root = self.fit_r(rows, labels, treatment, curr_depth=0, node=self.root,
                                   est_rows=est_rows, est_labels=est_labels, est_treatment=est_treatment)
        else:
            self.root = self.Node(col=-1, value=None, current_obj=0.0, effect=effect,
                                  p_val=0, treat_split=curr_split, node_depth=0)
            self.root = self.fit_r(rows, labels, treatment, curr_depth=0, node=self.root)

    def fit_r(self, rows, labels, treatment, curr_depth=0, node=None,
              est_rows=None, est_labels=None, est_treatment=None):

        if rows.shape[0] == 0:
            return node

        train_rows, val_rows, train_outcome, val_outcome, train_treat, val_treat = \
            train_test_split(rows, labels, treatment, shuffle=True, test_size=self.split_size)

        if self.val_honest:
            train_to_est_ratio = val_rows.shape[0] / train_rows.shape[0]
            node.samples = val_rows.shape[0]
        elif self.honest:
            train_to_est_ratio = est_rows.shape[0] / rows.shape[0]
            node.samples = est_rows.shape[0]
        else:
            train_to_est_ratio = -1
            node.samples = train_rows.shape[0]

        if curr_depth > self.tree_depth:
            self.tree_depth = curr_depth

        if self.max_depth == curr_depth:
            # node leaf number
            self.num_leaves += 1
            # add node leaf number to node class
            node.leaf_num = self.num_leaves
            node.leaf = True
            return node

        best_gain = 0.0
        best_attribute = None

        best_tb_obj = 0.0
        best_fb_obj = 0.0

        best_tb_split = 0.0
        best_fb_split = 0.0

        best_tb_var = 0.0
        best_fb_var = 0.0

        best_tb_mse = 0.0
        best_fb_mse = 0.0

        tb_var = 0.0
        fb_var = 0.0

        curr_depth += 1

        column_count = rows.shape[1]
        for col in range(0, column_count):
            # unique values
            column_values = np.unique(rows[:, col])
            unique_vals = column_values.copy()

            if self.max_values is not None:
                if self.max_values < 1:
                    idx = np.round(np.linspace(0, len(unique_vals) - 1, self.max_values * len(unique_vals))).astype(int)
                    unique_vals = unique_vals[idx]
                else:
                    idx = np.round(np.linspace(0, len(unique_vals) - 1, self.max_values)).astype(int)
                    unique_vals = unique_vals[idx]
            
            if self.quantile:
                if (isinstance(unique_vals[0], int) or isinstance(unique_vals[0], float)):
                    if len(unique_vals) > 7:  #find quantile
                        lspercentile = np.percentile(column_values, [8,20,40,56,68,82,95])
                    else:
                        lspercentile = np.percentile(unique_vals, [25,50,75])
                unique_vals = np.unique(lspercentile)

            if self.verbose:
                self.time = time.time() - self.start
                print("Depth: %d, Column: %d, Elapsed Time: %.3f" %( curr_depth-1, col, self.time))
                
            for value in unique_vals:
                # binary treatment splitting
                if self.eval_func == self.objective:
                    #split the data according to the value of col
                    (train_set1, train_set2, train_y1, train_y2, train_treat1, train_treat2) \
                        = divide_set(train_rows, train_outcome, train_treat, col, value)

                    if check_min_size(self.min_size, train_treat1) or \
                            check_min_size(self.min_size, train_treat2):
                        continue

                    (val_set1, val_set2, val_y1, val_y2, val_treat1, val_treat2) \
                        = divide_set(val_rows, val_outcome, val_treat, col, value)

                    val_size = self.split_size*self.min_size if self.split_size*self.min_size > 2 else 2
                    if check_min_size(val_size, val_treat1) or \
                            check_min_size(val_size, val_treat2):
                        continue

                    if not self.val_honest and self.honest:
                        (est_set1, est_set2, est_y1, est_y2, est_treat1, est_treat2) \
                            = divide_set(est_rows, est_labels, est_treatment, col, value)
                        if check_min_size(val_size, est_treat1) or \
                                check_min_size(val_size, est_treat2):
                            continue

                    if self.honest:
                        tb_num_cont, tb_num_treat = get_treat_size(train_treat1)
                        fb_num_cont, fb_num_treat = get_treat_size(train_treat2)
                        var1_treat, var1_control = variance(train_y1, train_treat1)
                        var2_treat, var2_control = variance(train_y2, train_treat2)
                        tb_var = (1 + train_to_est_ratio) * (
                                (var1_treat / (tb_num_treat + 1)) + (var1_control / (tb_num_cont + 1)))
                        fb_var = (1 + train_to_est_ratio) * (
                                (var2_treat / (fb_num_treat + 1)) + (var2_control / (fb_num_cont + 1)))

                    tb_eval, tb_mse = self.eval_func(train_y1, train_treat1, val_y1, val_treat1)
                    fb_eval, fb_mse = self.eval_func(train_y2, train_treat2, val_y2, val_treat2)

                    split_eval = (tb_eval + fb_eval) - (tb_var + fb_var)
                    gain = -(node.current_obj - node.variance) + split_eval

                    if gain > best_gain:
                        best_gain = gain
                        best_attribute = [col, value]
                        best_tb_obj, best_fb_obj = tb_eval, fb_eval
                        best_tb_var, best_fb_var = tb_var, fb_var
                        best_tb_mse, best_fb_mse = tb_mse, fb_mse

                # continuous treatment splitting
                if self.eval_func == self.objective_cont:

                    (train_set1, train_set2, train_y1, train_y2, train_treat1, train_treat2) \
                        = divide_set(train_rows, train_outcome, train_treat, col, value)

                    (val_set1, val_set2, val_y1, val_y2, val_treat1, val_treat2) \
                        = divide_set(val_rows, val_outcome, val_treat, col, value)

                    if np.unique(val_y1).shape[0] <= 1 or np.unique(val_y2).shape[0] <= 1 or \
                            np.unique(train_y1).shape[0] <= 1 or np.unique(train_y2).shape[0] <= 1:
                        continue

                    if not self.val_honest and self.honest:
                        (est_set1, est_set2, est_y1, est_y2, est_treat1, est_treat2) \
                            = divide_set(est_rows, est_labels, est_treatment, col, value)
                        if np.unique(est_y1).shape[0] <= 1 or np.unique(est_y1).shape[0] <= 1:
                            continue
                    

                    tb_effect, tb_eval, tb_split, tb_mse = self.eval_func(train_y1, train_treat1, val_y1, val_treat1)
                    fb_effect, fb_eval, fb_split, fb_mse = self.eval_func(train_y2, train_treat2, val_y2, val_treat2)
                    
                    if self.honest:
                        tb_num_cont, tb_num_treat = get_treat_size(train_treat1, treat_split=tb_split)
                        fb_num_cont, fb_num_treat = get_treat_size(train_treat2, treat_split=fb_split)
                        var1_treat, var1_control = variance(train_y1, train_treat1, treat_split=tb_split)
                        var2_treat, var2_control = variance(train_y2, train_treat2, treat_split=fb_split)
                        tb_var = (1 + train_to_est_ratio) * (
                                (var1_treat / (tb_num_treat + 1)) + (var1_control / (tb_num_cont + 1)))
                        fb_var = (1 + train_to_est_ratio) * (
                                (var2_treat / (fb_num_treat + 1)) + (var2_control / (fb_num_cont + 1)))

                    split_eval = (tb_eval + fb_eval)
                    gain = -0.5*node.current_obj + split_eval

                    if gain > best_gain:
                        best_gain = gain
                        best_attribute = (col, value)
                        best_tb_obj, best_fb_obj = tb_eval, fb_eval
                        # best_tb_var, best_fb_var = tb_var, fb_var
                        best_tb_split, best_fb_split = tb_split, fb_split
                        best_tb_mse, best_fb_mse = tb_mse, fb_mse
                        best_tb_effect, best_fb_effect = tb_effect,fb_effect

        if self.eval_func == self.objective:
            if best_gain > 0:
                node.col = best_attribute[0]
                node.value = best_attribute[1]

                (set1, set2, y1, y2, treat1, treat2) = divide_set(rows, labels, treatment, node.col, node.value)
                est_set1, est_set2, est_y1, est_y2, est_treat1, est_treat2 = [0] * 6

                if self.val_honest:
                    (use_set1, use_set2, use_y1, use_y2, use_treat1, use_treat2) \
                        = divide_set(val_rows, val_outcome, val_treat, node.col, node.value)
                elif self.honest:
                    (use_set1, use_set2, use_y1, use_y2, use_treat1, use_treat2) \
                        = divide_set(est_rows, est_labels, est_treatment, node.col, node.value)
                    est_set1, est_set2, est_y1, est_y2, est_treat1, est_treat2 \
                        = divide_set(est_rows, est_labels, est_treatment, node.col, node.value)
                else:
                    (use_set1, use_set2, use_y1, use_y2, use_treat1, use_treat2) \
                        = divide_set(train_rows, train_outcome, train_treat, node.col, node.value)

                best_tb_effect = self.effect(use_y1, use_treat1)
                best_fb_effect = self.effect(use_y2, use_treat2)
                tb_p_val = get_pval(use_y1, use_treat1)
                fb_p_val = get_pval(use_y2, use_treat2)

                self.obj = self.obj - (node.current_obj - node.variance) + (best_tb_obj + best_fb_obj -
                                                                            best_tb_var - best_fb_var)

                self.mse = self.mse - node.node_mse + best_tb_mse + best_fb_mse

                tb = self.Node(current_obj=best_tb_obj, effect=best_tb_effect, p_val=tb_p_val, node_var=best_tb_var,
                               node_depth=curr_depth, node_mse=best_tb_mse)
                fb = self.Node(current_obj=best_fb_obj, effect=best_fb_effect, p_val=fb_p_val, node_var=best_fb_var,
                               node_depth=curr_depth, node_mse=best_fb_mse)

                node.true_branch = self.fit_r(set1, y1, treat1,
                                              curr_depth=curr_depth, node=tb,
                                              est_rows=est_set1,
                                              est_labels=est_y1,
                                              est_treatment=est_treat1)
                node.false_branch = self.fit_r(set2, y2, treat2,
                                               curr_depth=curr_depth, node=fb,
                                               est_rows=est_set2,
                                               est_labels=est_y2,
                                               est_treatment=est_treat2)

                if node.effect > self.max:
                    self.max = node.effect
                if node.effect < self.min:
                    self.min = node.effect

                return node
                # min and max
            else:
                if node.effect > self.max:
                    self.max = node.effect
                if node.effect < self.min:
                    self.min = node.effect

                # node leaf number
                self.num_leaves += 1
                # add node leaf number to node class
                node.leaf_num = self.num_leaves
                node.leaf = True
                return node

        elif self.eval_func == self.objective_cont:
            if best_gain > 0:

                node.col = best_attribute[0]
                node.value = best_attribute[1]

                (set1, set2, y1, y2, treat1, treat2) = divide_set(rows, labels, treatment, node.col, node.value)
                est_set1, est_set2, est_y1, est_y2, est_treat1, est_treat2 = [0] * 6#

                
                #only used in effect, can be deleted to save space
#                 if self.val_honest:
#                     (use_set1, use_set2, use_y1, use_y2, use_treat1, use_treat2) \
#                         = divide_set(val_rows, val_outcome, val_treat, node.col, node.value)
#                 elif self.honest:
#                     (use_set1, use_set2, use_y1, use_y2, use_treat1, use_treat2) \
#                         = divide_set(est_rows, est_labels, est_treatment, node.col, node.value)
#                     est_set1, est_set2, est_y1, est_y2, est_treat1, est_treat2 \
#                         = divide_set(est_rows, est_labels, est_treatment, node.col, node.value)
#                 else:
#                     (use_set1, use_set2, use_y1, use_y2, use_treat1, use_treat2) \
#                         = divide_set(train_rows, train_outcome, train_treat, node.col, node.value)

                # best_tb_effect = self.effect(use_y1, use_treat1, treat_split=best_tb_split)
                # best_fb_effect = self.effect(use_y2, use_treat2, treat_split=best_fb_split)
                # tb_p_val = get_pval(use_y1, use_treat1, treat_split=best_tb_split)
                # fb_p_val = get_pval(use_y2, use_treat2, treat_split=best_fb_split)

                # self.obj = self.obj - (node.current_obj - node.variance) + (best_tb_obj + best_fb_obj -
                #                                                             best_tb_var - best_fb_var)
                self.obj = self.obj - (node.current_obj) + (best_tb_obj + best_fb_obj)

                self.mse = self.mse - node.node_mse + best_tb_mse + best_fb_mse
                # if self.use_mse:
                #     self.obj = self.obj - node.current_obj + best_tb_mse + best_fb_mse

                tb = self.Node(current_obj=best_tb_obj, effect=best_tb_effect, p_val=0,
                               treat_split=best_tb_split, node_mse=best_tb_mse)
                fb = self.Node(current_obj=best_fb_obj, effect=best_fb_effect, p_val=0,
                               treat_split=best_fb_split, node_mse=best_fb_mse)

                node.true_branch = self.fit_r(set1, y1, treat1,
                                              curr_depth=curr_depth, node=tb,
                                              est_rows=est_set1,
                                              est_labels=est_y1,
                                              est_treatment=est_treat1
                                              )
                node.false_branch = self.fit_r(set2, y2, treat2,
                                               curr_depth=curr_depth, node=fb,
                                               est_rows=est_set2,
                                               est_labels=est_y2,
                                               est_treatment=est_treat2
                                               )

                if node.effect > self.max:
                    self.max = node.effect
                if node.effect < self.min:
                    self.min = node.effect

                return node
            else:
                if node.effect > self.max:
                    self.max = node.effect
                if node.effect < self.min:
                    self.min = node.effect

                # node leaf number
                self.num_leaves += 1
                # add node leaf number to node class
                node.leaf_num = self.num_leaves
                node.leaf = True
                return node

    #output F score
    def objective(self, train_outcome, train_treatment, val_outcome, val_treatment):
        """Calculates the objective value

        outcome: the observed outcome vector
        treatment: the treatment vector
        """
        total_train = train_outcome.shape[0]
        total_val = val_outcome.shape[0]

        return_val = (-np.inf, -np.inf)

        if total_train == 0 or total_val == 0:
            return return_val

        if isinstance(train_outcome[0], str):
            train_outcome = string_to_int(train_outcome)
            val_outcome = string_to_int(val_outcome)

        train_effect = ace(train_outcome, train_treatment)
        val_effect = ace(val_outcome, val_treatment)

        # train_mse = total_val * (train_effect ** 2)
        # val_mse = total_val * (val_effect ** 2)
        # train_mse = (1-weight) * total_train * (train_effect ** 2)
        train_mse = (1 - self.weight) * total_train * (train_effect ** 2)#(1-λ)F
        cost = self.weight * total_val * np.abs(train_effect - val_effect)#λC

        if self.base_obj:
            obj = (train_mse - cost) / (np.abs(total_train - total_val) + 1)
            mse = total_train * (train_effect ** 2)
            if self.weight_obj:
                obj = total_train * obj
        else:
            train_mse = (1 - self.weight) * train_effect ** 2
            cost = self.weight * np.abs(train_effect - val_effect)
            obj = (train_mse - cost)
            mse = total_train * (train_effect ** 2)
            if self.weight_obj:
                obj = total_train * obj

        return obj, mse

    #output the best F and the best splitting
    def objective_cont(self, train_outcome, train_treatment, val_outcome, val_treatment):
        """Continuous case"""
        total_train = train_outcome.shape[0]
        t_nums = train_treatment.shape[1]
        
        return_val = (-np.inf, -np.inf, -np.inf, -np.inf)  
        
        if total_train == 0 or t_nums == 0:
            return return_val
 
        resource_used = 0
        obj_total = 0
        effect_total = 0
        split_result = {}
        step = 0
       
        if self.weight_pick == True:
            pp = np.mean(train_treatment, axis=0) + 0.005
            pp = pp / pp.sum()
        else:
            pp = np.ones(t_nums) / np.sum(np.ones(t_nums))
        for trt in list(np.random.choice(a=range(t_nums),size=t_nums, replace=False,p=pp.ravel())):
            train_treatment_i = train_treatment[:,trt]
    
            range_treatment = np.array(list(filter(lambda x:x<=1-resource_used, train_treatment[:,trt])))
            unique_treatment = np.unique(range_treatment)
            if unique_treatment.shape[0] == 1:
#                 print(step,resource_used,trt,unique_treatment,max(range_treatment))
                if step == 0:
                    return return_val
                else:
                    for i in split_result:
                        split_result[i] *= 1/resource_used
                    return effect_total*self.tnums/step, obj_total*self.tnums/step,split_result,obj_total*self.tnums/step
                #return return_val

            if len(unique_treatment) > 9: 
                lspercentile = np.percentile(unique_treatment, np.linspace(0,100,10))
                unique_treatment = np.unique(lspercentile)
            unique_treatment = (unique_treatment[1:] + unique_treatment[:-1]) / 2
            
           
 #            if isinstance(train_outcome[0], str):
#                 train_outcome = string_to_int(train_outcome)
            
            ############  
            if unique_treatment.shape[0]==0:
                continue
                 
            train_interval = np.hstack((np.zeros(1),unique_treatment,np.ones(1)))
            yy = np.tile(train_outcome, (unique_treatment.shape[0]+1, 1))
            tt = np.tile(train_treatment_i, (unique_treatment.shape[0]+1, 1))

            ti = np.transpose((np.transpose(tt) >= train_interval[:-1])  & (np.transpose(tt) < train_interval[1:]) )
            
            # do the min_size check on each_interval
            interval_num = np.sum(ti == 1, axis=1)
#             if np.min(interval_num)==0:
#                 print('np.min(interval_num)==0',train_treatment_i,train_interval)
            min_interval_size = np.where(interval_num >= 1)
            ti = ti[ min_interval_size]
            tt = tt[ min_interval_size]
            yy = yy[ min_interval_size]
           
            train_outcome_ii = np.sum((yy * (ti == 1)), axis=1) / np.sum(ti == 1, axis=1)            
            train_treatment_ii = ((train_interval[:-1]+train_interval[1:])/2 )[ min_interval_size]
                
            yyt = np.tile(train_outcome_ii, (unique_treatment.shape[0], 1))
            ttt = np.tile(train_treatment_ii, (unique_treatment.shape[0], 1))
            wallt = np.tile(train_interval, (unique_treatment.shape[0], 1)) 
            yyt = np.cumsum((wallt[:,1:]-wallt[:,:-1])[:,min_interval_size].reshape(yyt.shape)*yyt,axis=1)
            
            '''
            #smooth
            yyt = np.hstack((yyt[:,0].reshape((-1,1)),yyt,yyt[:,-1].reshape((-1,1))))
            yyt = (yyt[:,:-2]+yyt[:,1:-1]+yyt[:,2:])/3
            '''

            xt = np.transpose(np.transpose(ttt) > unique_treatment)
            ttt[xt] = 1
            ttt[np.logical_not(xt)] = 0

            # do the min_size check on training set
            treat_num = np.sum(ttt == 1, axis=1)
            cont_num = np.sum(ttt == 0, axis=1)
            min_size_idx = np.where(np.logical_and(treat_num >= self.min_size, cont_num >= self.min_size))

            unique_treatment = unique_treatment[min_size_idx]
            ttt = ttt[min_size_idx]
            yyt = yyt[min_size_idx]

            if ttt.shape[0] == 0:
                return return_val


            y_t_m_t = np.sum((yyt * (ttt == 1)), axis=1) / np.sum(ttt == 1, axis=1)
            y_c_m_t = np.sum((yyt * (ttt == 0)), axis=1) / np.sum(ttt == 0, axis=1)


            train_effect = y_t_m_t - y_c_m_t
            train_err = train_effect ** 2
            #obj = train_err
            obj = total_train * train_err

            argmax_obj = np.argmax(obj)
            obj_total += obj[argmax_obj]
            effect_total += np.abs(train_effect[argmax_obj])
            best_split = unique_treatment[argmax_obj]

            if resource_used+best_split>=1:
                best_split = 1- resource_used

            split_result[trt] = best_split
            resource_used += best_split
            # mse += train_err[argmax_obj]
            step += 1

            if resource_used == 1:
                # effect_total = effect_total*self.tnums/step
                # obj_total = obj_total*self.tnums/step
                break
            
            del train_treatment_i

        if resource_used<1:
            for i in split_result:
                split_result[i] *= 1/resource_used
        return effect_total, obj_total, split_result, obj_total

    def tree_to_dot(self, tree, feat_names, filename='tree', alpha=0.05, show_pval=True):
        filename = filename + '.dot'
        feat_names = col_dict(feat_names)
        with open(filename, 'w') as f:
            f.write('digraph Tree {\n')
            f.write('node [shape=box, fontsize=32] ;\n')
            f.write('edge [fontsize=24] ;\n')
            self.tree_to_dot_r(tree, feat_names, f, counter=0, alpha=alpha, show_pval=show_pval)
            f.write("}")

    @staticmethod
    def dot_to_png(dot_filename="tree", output_file=None, extension="png"):

        if output_file is None:
            command = ["dot", "-T" + extension, "-Gdpi=200", dot_filename + '.dot', "-o",
                       dot_filename + "." + extension]
        else:
            command = ["dot", "-T" + extension, "-Gdpi=200", dot_filename + '.dot', "-o", output_file + "." + extension]
        try:
            if os.name == 'nt':
                subprocess.check_call(command, shell=True)
            else:
                subprocess.check_call(command)
        except subprocess.CalledProcessError:
            exit("Could not run dot, ie graphviz, to "
                 "produce visualization")

#     @staticmethod
#     def effect(outcome, treatment, treat_split=None):
#         total = outcome.shape[0]

#         return_val = (-np.inf, -np.inf)

#         if total == 0:
#             return return_val

#         if isinstance(outcome[0], str):
#             outcome = string_to_int(outcome)

#         treat_vect = treatment

        
#         if treat_split is not None:
#             res = {}
#             for i,j in zip(treatment,outcome):
#                 if i not in res:
#                     res[i]= []
#                 res[i].append(j)
            
      
#             res = {i:sum(j)/len(j) for i,j in res.items()}
  
#             treatment, outcome = np.array(list(zip(*res.items())))
            
#             outcome = outcome[treatment.argsort()]
#             treatment = np.sort(treatment)
#             interval = (treatment[1:]+treatment[:-1])/2
            
#             wall0 = np.concatenate((np.array([0]),interval[interval<=treat_split],np.array([treat_split])))
#             wall1 = np.concatenate((interval[interval>treat_split],np.array([1])))
#             yy1 = np.cumsum((wall0[1:]-wall0[:-1])*outcome[:len(wall0)-1])
#             yy2 = np.cumsum((wall1[1:]-wall1[:-1])*outcome[-len(wall1)+1:])
            
#             #smooth
#             yy1 = np.hstack((np.array([yy1[0]]),yy1,np.array([yy1[-1]])))
#             yy1 = (yy1[:-2]+yy1[1:-1]+yy1[2:])/3
#             yy2 = np.hstack((np.array([yy2[0]]),yy2,np.array([yy2[-1]])))
#             yy2 = (yy2[:-2]+yy2[1:-1]+yy2[2:])/3
            
#             mu0 = np.mean(yy1)
#             mu1 = np.mean(yy2)
            
#             effect = mu1-mu0

#         return effect
    
    @staticmethod
    def effect(outcome, treatment, treat_split=None):
        total = outcome.shape[0]

        return_val = (-np.inf, -np.inf)

        if total == 0:
            return return_val

        if isinstance(outcome[0], str):
            outcome = string_to_int(outcome)

        treat_vect = treatment

        
        if treat_split is not None:            
            
            
            res = {}
            for i,j in zip(treatment,outcome):
                if i not in res:
                    res[i]= []
                res[i].append(j)
            
      
            res = {i:sum(j)/len(j) for i,j in res.items()}
  
            treatment, outcome = np.array(list(zip(*res.items())))
            
            outcome = outcome[treatment.argsort()]
            treatment = np.sort(treatment)
            interval = (treatment[1:]+treatment[:-1])/2
               
            
            wall = np.hstack((np.zeros(1),interval,np.ones(1)))
            outcome = np.cumsum((wall[1:]-wall[:-1])*outcome)
            #smooth
            outcome = np.hstack((outcome[0],outcome,outcome[-1]))
            outcome = (outcome[:-2]+outcome[1:-1]+outcome[2:])/3


            x = (treatment > treat_split)
            treatment[x] = 1
            treatment[np.logical_not(x)] = 0

            mu1 = np.sum(outcome * (treatment == 1)) / np.sum(treatment == 1)
            mu0 = np.sum(outcome * (treatment == 0)) / np.sum(treatment == 0)
            
            effect = mu1-mu0

        return effect
    
    def plot_tree(self, feat_names=None, training_data=None, file="tree", alpha=0.05, show_pval=True,
                  create_png=True, extension="png"):

        if feat_names is None:
            if training_data is not None:
                feat_names = []
                for i in range(training_data.shape[0]):
                    feat_names.append("att_{}".format(i))
            else:
                print("You need either feature names or training data")

        name_split = file.split('/')
        if len(name_split) > 1:
            img_folder = name_split[0:-1]
            file_name = name_split[-1]

            img_folder = '/'.join(img_folder)

            dot_folder = img_folder + '/dot_folder/'

            check_dir(img_folder + '/')
            check_dir(dot_folder)

            dot_file_name = dot_folder + file_name
            img_file_name = file
            self.tree_to_dot(self.root, feat_names, dot_file_name, alpha=alpha, show_pval=show_pval)
            if create_png:
                self.dot_to_png(dot_file_name, img_file_name, extension=extension)
        else:
            self.tree_to_dot(self.root, feat_names, file, alpha=alpha, show_pval=show_pval)
            if create_png:
                self.dot_to_png(file, extension=extension)

    def tree_to_dot_r(self, node, feat_names, f, counter, alpha=0.05, show_pval=True):
        curr_node = counter
        f.write(str(counter) + ' ')
        f.write('[')
        node_str = list(['label=\"'])

        # number of samples
        node_str.append('samples = ')
        node_str.append(str(node.samples))

        # add entropy/ATE here
        node_str.append('\\neffect = ')
        ace_str = '%.3f' % node.effect
        node_str.append(ace_str)

        # p_values
        if show_pval:
            node_str.append('\\np = ')
            p_val_str = '%.3f' % node.p_val
            node_str.append(p_val_str)

        if node.treat_split is not None:
            if curr_node == 0:
                node_str.append('\\nTrigger: ')
                node_str.append('trigger > ')
            else:
                node_str.append('\\ntrigger > ')
            treat_str = '%s' % node.treat_split
            node_str.append(treat_str)

        if not node.leaf:
            sz_col = 'Column %s' % node.col
            if feat_names and sz_col in feat_names:
                sz_col = feat_names[sz_col]
            if isinstance(node.value, int):
                decision = '%s >= %s' % (sz_col, node.value)
                # opp_decision = '%s < %s' % (sz_col, tree.value)
            elif isinstance(node.value, float):
                decision = '%s >= %.3f' % (sz_col, node.value)
                # opp_decision = '%s < %.3f' % (sz_col, tree.value)
            else:
                decision = '%s == %s' % (sz_col, node.value)
                # opp_decision = '%s =/=' % (sz_col, tree.value)
            node.feature_split = decision

            # if curr_node == 0:
            #     node_str.append('Splitting feature: ')
            node_str.append('\\n' + decision + '\\n')

        node_str.append('\"')

        node_str.append(", style=filled")
        effect_range = np.linspace(self.min, self.max, 10)
        effect = node.effect
        color = '\"#ffffff\"'
        color_idx = 0
        for idx, effect_r in enumerate(effect_range[:-1]):
            if effect_range[idx] <= effect <= effect_range[idx + 1]:
                color = "\"/blues9/%i\"" % (idx + 1)
                color_idx = idx
                break

        color_str = ", fillcolor=" + color
        node_str.append(color_str)
        # node_str.append("style=filled, color=\"/blues3/2\"")

        if color_idx >= 7:
            font_color = ", fontcolor=white"
            node_str.append(font_color)

        if node.p_val <= alpha:
            # node_str.append(", shape=box")
            # node_str.append(", sides=4")
            # node_str.append(", peripheries=3")
            node_str.append(", color=red")
            node_str.append(", penwidth=3.0")

        node_str.append('] ;\n')
        f.write(''.join(node_str))

        # start doing the branches
        counter = counter + 1
        if node.true_branch is not None:
            if curr_node == 0:
                f.write(str(curr_node) + ' -> ' + str(counter) +
                        ' [labeldistance=2.5, labelangle=45, headlabel=\"True\"] ;\n')
            else:
                f.write(str(curr_node) + ' -> ' + str(counter) + ' ;\n')
            # f.write(str(curr_node) + ' -> ' + str(counter) +
            #         ' [labeldistance=2.5, labelangle=45, headlabel=' + decision + '];\n')
            counter = self.tree_to_dot_r(node.true_branch, feat_names, f, counter, alpha=alpha, show_pval=show_pval)
        if node.false_branch is not None:
            if curr_node == 0:
                f.write(str(curr_node) + ' -> ' + str(counter) +
                        ' [labeldistance=2.5, labelangle=-45, headlabel=\"False\"] ;\n')
            else:
                f.write(str(curr_node) + ' -> ' + str(counter) + ' ;\n')
            # f.write(str(curr_node) + ' -> ' + str(counter) +
            #         ' [labeldistance=2.5, labelangle=45, headlabel=' + opp_decision + '];\n')
            counter = self.tree_to_dot_r(node.false_branch, feat_names, f, counter, alpha=alpha, show_pval=show_pval)

        return counter

    def prune(self, alpha=.05):
        """Prunes the obtained tree according to the statistical significance gain. """

        def prune_r(node):

            if node.true_branch is None or node.false_branch is None:
                return

            # recursive call for each branch
            if not node.true_branch.leaf:
                prune_r(node.true_branch)
            if not node.false_branch.leaf:
                prune_r(node.false_branch)

            # merge leaves (potentially)
            if node.true_branch.leaf and node.false_branch.leaf:

                # Get branch labels
                tb = node.true_branch
                fb = node.false_branch

                tb_pval = tb.p_val
                fb_pval = fb.p_val

                if tb_pval > alpha and fb_pval > alpha:
                    node.leaf_num = node.true_branch.leaf_num
                    node.true_branch, node.false_branch = None, None
                    node.leaf = True
                    self.num_leaves = self.num_leaves - 1
                    self.obj = self.obj - (tb.current_obj + fb.current_obj - tb.variance - fb.variance) + \
                               node.current_obj - node.variance
                    self.mse = self.mse - (tb.node_mse + fb.node_mse) + node.node_mse
                    if tb.node_depth == self.tree_depth:
                        self.tree_depth = self.tree_depth - 1

        prune_r(self.root)

    def predict(self, test_data, return_features=False, variables=None, return_groups=False):

        if return_features:
            if self.root.feature_name is None:
                if variables is not None:
                    self.feature_split_labels(variables)
                else:
                    print("You need variable names")
                    return_features = False

        def classify_r(node, observation, features=None):
            if node.leaf:
                if features is not None:
                    return node.leaf_num, node.treat_split, node.effect, features
                else:
                    return node.leaf_num, node.treat_split, node.effect
            else:
                v = observation[node.col]
                if isinstance(v, int) or isinstance(v, float):
                    if v >= node.value:
                        branch = node.true_branch
                        if isinstance(v, int):
                            decision_str = "%s >= %d" % (node.feature_name, v)
                        else:
                            decision_str = "%s >= %.3f" % (node.feature_name, v)
                    else:
                        branch = node.false_branch
                        if isinstance(v, int):
                            decision_str = "%s < %d" % (node.feature_name, v)
                        else:
                            decision_str = "%s < %.3f" % (node.feature_name, v)
                else:
                    if v == node.value:
                        branch = node.true_branch
                        decision_str = "%s == %s" % (node.feature_name, v)
                    else:
                        branch = node.false_branch
                        decision_str = "%s != %s" % (node.feature_name, v)

            if features is not None:
                features.append(decision_str)
            return classify_r(branch, observation, features=features)

        if len(test_data.shape) == 1:
            leaf_results = classify_r(self.root, test_data)
            return leaf_results

        num_test = test_data.shape[0]

        leaf_results = np.zeros(num_test)
        leaf_treat_split = np.array([{} for i in range(num_test)])
        predict = np.zeros(num_test)

        test_feature_lists = []
        for i in range(num_test):
            test_example = test_data[i, :]
            if return_features:
                features_list = []
                leaf_results[i], leaf_treat_split[i], predict[i], features_list = classify_r(self.root, test_example,
                                                                                             features=features_list)
                test_feature_lists.append(features_list)
            else:
                leaf_results[i], leaf_treat_split[i], predict[i] = classify_r(self.root, test_example)

        if return_features:
            if return_groups and self.cont:
                return predict, leaf_results, leaf_treat_split, test_feature_lists
            elif not return_groups and self.cont:
                return predict, leaf_treat_split, test_feature_lists
            elif return_groups and not self.cont:
                return predict, leaf_results, test_feature_lists
            else:
                return predict, test_feature_lists
        else:
            if return_groups and self.cont:
                return predict, leaf_results, leaf_treat_split
            elif not return_groups and self.cont:
                return predict, leaf_treat_split
            elif return_groups and not self.cont:
                return predict, leaf_results
            else:
                return predict

    def feature_split_labels(self, variable_names):

        variable_names = col_dict(variable_names)

        def feature_split_labels_r(node, feat_names):

            if not node.leaf:
                sz_col = 'Column %s' % node.col
                if feat_names and sz_col in feat_names:
                    sz_col = feat_names[sz_col]
                decision = '%s' % sz_col
                node.feature_name = decision

                sz_col = 'Column %s' % node.col
                if feat_names and sz_col in feat_names:
                    sz_col = feat_names[sz_col]
                if isinstance(node.value, int):
                    decision = '%s >= %s' % (sz_col, node.value)
                    # opp_decision = '%s < %s' % (sz_col, tree.value)
                elif isinstance(node.value, float):
                    decision = '%s >= %.3f' % (sz_col, node.value)
                    # opp_decision = '%s < %.3f' % (sz_col, tree.value)
                else:
                    decision = '%s == %s' % (sz_col, node.value)
                    # opp_decision = '%s =/=' % (sz_col, tree.value)
                node.feature_split = decision

            # start doing the branches
            if node.true_branch is not None:
                feature_split_labels_r(node.true_branch, feat_names)
            if node.false_branch is not None:
                feature_split_labels_r(node.false_branch, feat_names)

        feature_split_labels_r(self.root, variable_names)

    def get_variables_used(self, variable_names=None, cat=False):

        if self.root.feature_name is None:
            if variable_names is not None:
                self.feature_split_labels(variable_names)

        def get_variables_r(node, list_vars, list_depths):

            if node.leaf:
                return list_vars, list_depths
            else:
                if cat:
                    if '==' in node.feature_split:
                        # list_fs = node.feature_split.replace(" ", "").split("==")
                        list_fs = node.feature_split.split("==")
                        list_fs = [i.strip() for i in list_fs]
                        to_append = "_".join(list_fs)
                        # list_vars.append(to_append)
                        if to_append not in list_vars:
                            list_vars.append(to_append)
                            list_depths.append(node.depth)
                    else:
                        # list_vars.append(node.feature_name)
                        if node.feature_name not in list_vars:
                            list_vars.append(node.feature_name)
                            list_depths.append(node.depth)
                else:
                    # list_vars.append(node.feature_name)
                    if node.feature_name not in list_vars:
                        list_vars.append(node.feature_name)
                        list_depths.append(node.depth)
                list_vars = get_variables_r(node.true_branch, list_vars, list_of_depths)
                list_vars = get_variables_r(node.false_branch, list_vars, list_of_depths)

                return list_vars, list_depths

        list_of_vars = []
        list_of_depths = []
        list_of_vars, list_of_depths = get_variables_r(self.root, list_of_vars, list_of_depths)

        sorted_vars = []
        sorted_idx = np.argsort(list_of_depths)
        for i in sorted_idx:
            sorted_vars.append(list_of_vars[i])

        return sorted_vars
